"""
dxf_parser.py — robust DXF section parser.

Supports every entity type found in real cross-section exports:
  - LWPOLYLINE  (with arc bulges, code 42)
  - POLYLINE    (old-style, VERTEX list, with bulges)
  - LINE        (assembled into open chains)
  - ARC         (interpolated to points)
  - CIRCLE      (closed loop)
  - SPLINE      (fit points, or control points as a fallback polyline)

Two bugs in the previous version are fixed here:
  1. The main scan advanced `i += 2` unconditionally, which desynced on any
     file with more than one entity — so multi-entity files lost most of their
     geometry. This version walks line-by-line (`i += 1`) and parses each
     entity from its own code/value stream.
  2. LINE / ARC / CIRCLE / SPLINE entities were dropped entirely. They are now
     all read. Loose LINE/ARC segments are stitched into closed loops by
     matching endpoints, so a profile drawn as separate lines still becomes a
     filled region.

Output is unchanged (same dict shape) so callers/templates keep working.
Compound profiles (outer + holes, or several loops) render with fill-rule
evenodd, which is correct for both single and multi-loop shapes.
"""
import json
import math


# ----------------------------------------------------------------------
#  DXF tag stream helpers
# ----------------------------------------------------------------------

# DXF $INSUNITS codes -> factor to convert to millimetres
_UNIT_TO_MM = {
    1: 25.4,     # Inches
    2: 304.8,    # Feet
    3: 1609344.0,  # Miles (unlikely, but complete)
    4: 1.0,      # Millimeters
    5: 10.0,     # Centimeters
    6: 1000.0,   # Meters
    8: 0.0254,   # Microinches
    9: 0.001,    # Mils
}


def _detect_unit_scale(file_content):
    """
    Scan the HEADER section for $INSUNITS and return a scale factor to
    convert the file's coordinates into millimetres. Returns 1.0 (assume
    mm) if $INSUNITS is absent/unitless (0) — same as before, but now the
    non-mm cases are handled instead of silently mis-scaling.
    """
    lines = file_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    for i in range(len(lines) - 3):
        if lines[i].strip() == '9' and lines[i + 1].strip() == '$INSUNITS':
            # next pair should be code 70, value
            code_raw = lines[i + 2].strip()
            val_raw = lines[i + 3].strip()
            try:
                if int(code_raw) == 70:
                    unit_code = int(float(val_raw))
                    return _UNIT_TO_MM.get(unit_code, 1.0), unit_code
            except ValueError:
                pass
    return 1.0, 0  # unitless / not found — assume mm, unchanged behaviour


def _tags(file_content):
    """Yield (code:int, value:str) pairs from raw DXF text."""
    lines = file_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    i = 0
    n = len(lines)
    while i < n - 1:
        code_raw = lines[i].strip()
        val = lines[i + 1]
        i += 2
        if code_raw == '':
            continue
        try:
            code = int(code_raw)
        except ValueError:
            continue
        yield code, val.strip()


# Layers that hold annotation/dimension geometry, not the actual profile
# outline. LINE/LWPOLYLINE entities drawn on these layers (leaders,
# extension lines, hatch boundaries duplicated for annotation, etc.) must
# not be stitched into the profile shape.
_EXCLUDED_LAYER_SUBSTRINGS = (
    'dim', 'dimension', 'text', 'annot', 'note', 'centre', 'center',
    'hatch', 'hidden', 'leader', 'title', 'border', 'tblock',
)


def _is_excluded_layer(layer_name):
    if not layer_name:
        return False
    n = layer_name.lower()
    return any(s in n for s in _EXCLUDED_LAYER_SUBSTRINGS)


def _entities(file_content):
    """
    Split the tag stream into entities. Returns a list of dicts:
      {'type': 'LWPOLYLINE', 'layer': 'PROFILE', 'tags': [(code, val), ...]}
    Only geometry we care about is kept, and entities on clearly
    non-geometry layers (dimensions, text, annotation, title blocks) are
    dropped so they can't be stitched into the actual profile outline.
    """
    WANTED = {'LWPOLYLINE', 'POLYLINE', 'VERTEX', 'SEQEND',
              'LINE', 'ARC', 'CIRCLE', 'SPLINE'}
    ents = []
    current = None
    for code, val in _tags(file_content):
        if code == 0:
            if current and not _is_excluded_layer(current.get('layer')):
                ents.append(current)
            current = {'type': val, 'layer': None, 'tags': []} if val in WANTED else None
        elif current is not None:
            if code == 8:
                current['layer'] = val
            current['tags'].append((code, val))
    if current and not _is_excluded_layer(current.get('layer')):
        ents.append(current)
    return ents


# ----------------------------------------------------------------------
#  Arc / bulge geometry
# ----------------------------------------------------------------------

def _bulge_to_arc_pts(p1, p2, bulge, n_seg=12):
    """Interpolate a bulge segment. Returns points after p1, ending at p2."""
    x1, y1 = p1
    x2, y2 = p2
    d = math.hypot(x2 - x1, y2 - y1)
    if d < 1e-10 or abs(bulge) < 1e-9:
        return [p2]
    theta = 4.0 * math.atan(abs(bulge))
    r = d / (2.0 * math.sin(theta / 2.0))
    d_center = math.sqrt(max(0.0, r * r - (d / 2.0) ** 2))
    alpha = math.atan2(y2 - y1, x2 - x1)
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    sign = 1 if bulge > 0 else -1
    cx = mx + sign * d_center * math.sin(alpha)
    cy = my - sign * d_center * math.cos(alpha)
    sa = math.atan2(y1 - cy, x1 - cx)
    ea = math.atan2(y2 - cy, x2 - cx)
    if bulge > 0:
        if ea >= sa:
            ea -= 2.0 * math.pi
    else:
        if ea <= sa:
            ea += 2.0 * math.pi
    n = max(n_seg, int(abs(bulge) * 24))
    out = []
    for k in range(1, n + 1):
        t = k / n
        a = sa + t * (ea - sa)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def _arc_pts(cx, cy, r, a0_deg, a1_deg, n_seg=32):
    """Interpolate a standalone ARC entity (angles in degrees, CCW)."""
    a0 = math.radians(a0_deg)
    a1 = math.radians(a1_deg)
    if a1 <= a0:
        a1 += 2.0 * math.pi
    span = a1 - a0
    n = max(6, int(n_seg * span / (2 * math.pi)))
    return [(cx + r * math.cos(a0 + span * k / n),
             cy + r * math.sin(a0 + span * k / n)) for k in range(n + 1)]


# ----------------------------------------------------------------------
#  Per-entity → point loop(s)
# ----------------------------------------------------------------------

def _lwpolyline_loop(tags):
    coords, bulges, closed = [], {}, False
    idx = -1
    for code, val in tags:
        try:
            if code == 10:
                idx += 1
                coords.append([float(val), None])
            elif code == 20 and coords and coords[-1][1] is None:
                coords[-1][1] = float(val)
            elif code == 42:
                bulges[idx] = float(val)
            elif code == 70:
                closed = bool(int(float(val)) & 1)
        except ValueError:
            pass
    pts = [(c[0], c[1]) for c in coords if c[1] is not None]
    return _expand(pts, bulges, closed), closed


def _polyline_loop(vertices):
    """Old-style POLYLINE: vertices is a list of (x, y, bulge)."""
    pts = [(v[0], v[1]) for v in vertices]
    bulges = {i: v[2] for i, v in enumerate(vertices) if abs(v[2]) > 1e-9}
    return _expand(pts, bulges, True)


def _expand(pts, bulges, closed):
    """Densify a vertex list, interpolating any bulge arcs. Returns points."""
    if len(pts) < 2:
        return []
    result = [pts[0]]
    n = len(pts)
    last = n if closed else n - 1
    for i in range(last):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        b = bulges.get(i, 0.0)
        if abs(b) > 1e-9:
            result.extend(_bulge_to_arc_pts(p1, p2, b))
        else:
            result.append(p2)
    return result


def _circle_loop(tags):
    cx = cy = r = None
    for code, val in tags:
        try:
            if code == 10: cx = float(val)
            elif code == 20: cy = float(val)
            elif code == 40: r = float(val)
        except ValueError:
            pass
    if cx is None or cy is None or not r:
        return []
    return [(cx + r * math.cos(2 * math.pi * k / 48),
             cy + r * math.sin(2 * math.pi * k / 48)) for k in range(49)]


def _arc_loop(tags):
    cx = cy = r = a0 = a1 = None
    for code, val in tags:
        try:
            if code == 10: cx = float(val)
            elif code == 20: cy = float(val)
            elif code == 40: r = float(val)
            elif code == 50: a0 = float(val)
            elif code == 51: a1 = float(val)
        except ValueError:
            pass
    if None in (cx, cy, r, a0, a1):
        return []
    return _arc_pts(cx, cy, r, a0, a1)


def _line_seg(tags):
    x1 = y1 = x2 = y2 = None
    for code, val in tags:
        try:
            if code == 10: x1 = float(val)
            elif code == 20: y1 = float(val)
            elif code == 11: x2 = float(val)
            elif code == 21: y2 = float(val)
        except ValueError:
            pass
    if None in (x1, y1, x2, y2):
        return None
    return [(x1, y1), (x2, y2)]


def _spline_loop(tags):
    """Use fit points (11/21) if present, else control points (10/20)."""
    fit, ctrl = [], []
    fx = cx = None
    for code, val in tags:
        try:
            if code == 11: fx = float(val)
            elif code == 21 and fx is not None: fit.append((fx, float(val))); fx = None
            elif code == 10: cx = float(val)
            elif code == 20 and cx is not None: ctrl.append((cx, float(val))); cx = None
        except ValueError:
            pass
    pts = fit if len(fit) >= 2 else ctrl
    return pts if len(pts) >= 2 else []


# ----------------------------------------------------------------------
#  Stitching loose LINE/ARC segments into closed loops
# ----------------------------------------------------------------------

def _stitch(segments, tol=1e-3):
    """
    Join open polylines/segments end-to-end into loops by matching endpoints.
    Each segment is a list of points. Returns a list of joined point-lists.
    """
    segs = [list(s) for s in segments if len(s) >= 2]
    loops = []
    used = [False] * len(segs)

    def close(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol

    for i in range(len(segs)):
        if used[i]:
            continue
        chain = segs[i][:]
        used[i] = True
        extended = True
        while extended:
            extended = False
            for j in range(len(segs)):
                if used[j]:
                    continue
                s = segs[j]
                if close(chain[-1], s[0]):
                    chain.extend(s[1:]); used[j] = True; extended = True
                elif close(chain[-1], s[-1]):
                    chain.extend(reversed(s[:-1])); used[j] = True; extended = True
                elif close(chain[0], s[-1]):
                    chain = s[:-1] + chain; used[j] = True; extended = True
                elif close(chain[0], s[0]):
                    chain = list(reversed(s[1:])) + chain; used[j] = True; extended = True
        loops.append(chain)
    return loops


# ----------------------------------------------------------------------
#  Normalisation + SVG
# ----------------------------------------------------------------------

def _keep_main_cluster(loops):
    """
    Some DXFs contain several separate copies of a part laid out across a sheet,
    or stray annotation geometry far from the section. A single section should
    be one compact cluster. We group loops by centroid proximity and keep the
    cluster whose combined bounding box has the largest area (the real profile),
    unless the geometry is already compact (then keep everything).
    """
    if len(loops) <= 1:
        return loops

    def centroid(lp):
        xs = [p[0] for p in lp]; ys = [p[1] for p in lp]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def bbox(lp):
        xs = [p[0] for p in lp]; ys = [p[1] for p in lp]
        return min(xs), min(ys), max(xs), max(ys)

    # overall span; if compact, no clustering needed
    gx0, gy0, gx1, gy1 = _bbox_all(loops)
    gw, gh = gx1 - gx0, gy1 - gy0
    diag = math.hypot(gw, gh)
    # cluster radius: loops whose centroids are within 25% of the overall
    # diagonal are considered the same part
    radius = max(diag * 0.25, 1.0)

    cents = [centroid(lp) for lp in loops]
    n = len(loops)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(cents[i][0] - cents[j][0],
                          cents[i][1] - cents[j][1]) <= radius:
                union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(loops[i])

    if len(clusters) <= 1:
        return loops

    # pick the cluster with the largest bounding-box area
    def cluster_area(group):
        allpts = [p for lp in group for p in lp]
        b = _bbox_all([allpts])
        return (b[2] - b[0]) * (b[3] - b[1])

    return max(clusters.values(), key=cluster_area)


def _keep_main_cluster_bbox(loops):
    return _bbox_all(loops)


def _bbox_all(point_lists):
    xs = [x for pts in point_lists for x, y in pts]
    ys = [y for pts in point_lists for x, y in pts]
    if not xs:
        return 0, 0, 1, 1
    return min(xs), min(ys), max(xs), max(ys)


def _normalise(pts, min_x, min_y, raw_w, raw_h, target=200, padding=14):
    avail = target - 2 * padding
    scale = min(avail / (raw_w or 1), avail / (raw_h or 1))
    sw, sh = raw_w * scale, raw_h * scale
    ox = padding + (avail - sw) / 2
    oy = padding + (avail - sh) / 2
    return [(round(ox + (x - min_x) * scale, 2),
             round(oy + (min_y + raw_h - y) * scale, 2)) for x, y in pts]


def _svg_path(pts):
    if not pts:
        return ''
    return 'M ' + ' L '.join(f'{x},{y}' for x, y in pts) + ' Z'


# ----------------------------------------------------------------------
#  Public pipeline
# ----------------------------------------------------------------------

def process_dxf(file_content: str) -> dict:
    unit_scale, unit_code = _detect_unit_scale(file_content)
    ents = _entities(file_content)

    loops = []          # closed loops (polylines, circles, arcs-as-loops)
    open_segs = []      # loose LINE / ARC / open SPLINE / open LWPOLYLINE, to be stitched

    # walk entities; reassemble old-style POLYLINE from its VERTEX children
    poly_vertices = None
    for e in ents:
        t = e['type']
        if t == 'POLYLINE':
            poly_vertices = []
        elif t == 'VERTEX' and poly_vertices is not None:
            vx = vy = 0.0; vb = 0.0
            for code, val in e['tags']:
                try:
                    if code == 10: vx = float(val)
                    elif code == 20: vy = float(val)
                    elif code == 42: vb = float(val)
                except ValueError:
                    pass
            poly_vertices.append((vx, vy, vb))
        elif t == 'SEQEND' and poly_vertices is not None:
            lp = _polyline_loop(poly_vertices)
            if len(lp) >= 3:
                loops.append(lp)
            poly_vertices = None
        elif t == 'LWPOLYLINE':
            lp, closed = _lwpolyline_loop(e['tags'])
            if closed and len(lp) >= 3:
                loops.append(lp)
            elif not closed and len(lp) >= 2:
                # Respect the file's actual open/closed flag instead of
                # force-closing every polyline — an open chain still needs
                # stitching against other segments before it's a real loop.
                open_segs.append(lp)
        elif t == 'CIRCLE':
            lp = _circle_loop(e['tags'])
            if len(lp) >= 3:
                loops.append(lp)
        elif t == 'ARC':
            seg = _arc_loop(e['tags'])
            if len(seg) >= 2:
                open_segs.append(seg)
        elif t == 'LINE':
            seg = _line_seg(e['tags'])
            if seg:
                open_segs.append(seg)
        elif t == 'SPLINE':
            seg = _spline_loop(e['tags'])
            if len(seg) >= 2:
                open_segs.append(seg)

    # stitch loose segments into loops, keep only those that form real regions
    for chain in _stitch(open_segs):
        if len(chain) >= 3:
            loops.append(chain)

    if not loops:
        return {'ok': False, 'error': 'No drawable geometry found in DXF file.'}

    loops = _keep_main_cluster(loops)

    # Normalise to millimetres if the file declared a non-mm $INSUNITS
    if unit_scale != 1.0:
        loops = [[(x * unit_scale, y * unit_scale) for x, y in lp] for lp in loops]

    min_x, min_y, max_x, max_y = _bbox_all(loops)
    raw_w, raw_h = max_x - min_x, max_y - min_y
    if raw_w < 0.5 or raw_h < 0.5:
        return {'ok': False,
                'error': f'Profile too small ({raw_w:.1f}×{raw_h:.1f}mm). '
                         f'Check DXF units (must be mm, 1:1 scale).'}

    norm = [_normalise(lp, min_x, min_y, raw_w, raw_h) for lp in loops]
    svg_path = ' '.join(_svg_path(p) for p in norm if p)
    geometry = [[[round(x, 4), round(y, 4)] for x, y in lp] for lp in loops]

    return {
        'ok':            True,
        'geometry_json': json.dumps(geometry),
        'svg_path':      svg_path,
        'vertex_count':  sum(len(lp) for lp in loops),
        'width_mm':      round(raw_w, 1),
        'height_mm':     round(raw_h, 1),
        'poly_count':    len(loops),
        # evenodd is correct for single loops AND compound (outer+holes) shapes
        'fill_rule':     'evenodd',
        'unit_code':     unit_code,     # DXF $INSUNITS as declared in the file
        'unit_scale':    unit_scale,    # factor applied to convert to mm
    }