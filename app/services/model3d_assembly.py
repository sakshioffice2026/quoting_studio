"""
app/services/model3d_assembly.py — per-role member sweep 3D builder.
VERSION: 3.0  (direct-plane placement, butt joints, full DXF loop support)

THE core 3D pipeline of Quoting Studio:
  2D design (panes)  →  member graph (frame_assembly.py)
                     →  each member gets its role's DXF profile section
                     →  section extruded along the member axis
                     →  assembled door / window

Geometry approach (final):
  * Cross-section polygon (u = across bar, v = through-wall depth) is
    extruded along +Z by the member length, then mapped into world space
    with ONE axis permutation — no chained rotations, no mitre boolean cuts.
      horizontal member: (u,v,length) → (Y,Z,X)
      vertical   member: (u,v,length) → (X,Z,Y)
  * Butt joints only — frame_assembly already sizes every member to its
    exact cut length (jambs slot between head and cill), so members meet
    without overlap. This is how real aluminium frames are assembled.
  * DXF loops: outer ring + inner rings (chambers) are honoured; shapely
    builds the polygon with holes and trimesh triangulates it.

Verify deployed version:  grep "^VERSION" app/services/model3d_assembly.py
"""
from __future__ import annotations
import io, os, math, logging, tempfile
logger = logging.getLogger(__name__)

_GLASS_RGBA = (140, 190, 205, 110)
_MIN_DEPTH  = 20.0     # degenerate-trace guard only. Real PWQ sections go
                       # as shallow as 27 mm (meeting stile) / 58 mm (sash),
                       # so the clamp must stay below them.

# Axis permutation matrices (4×4, homogeneous).  det = +1 for both — pure
# rotations, so face winding / normals stay correct.
#   horizontal: local (u,v,w) → world (w,u,v)   [X=w len, Y=u bar, Z=v depth]
_PERM_H = [[0.0, 0.0, 1.0, 0.0],
           [1.0, 0.0, 0.0, 0.0],
           [0.0, 1.0, 0.0, 0.0],
           [0.0, 0.0, 0.0, 1.0]]
#   vertical:   local (u,v,w) → world (v,w,u)?? — we need X=u, Y=w, Z=v.
#   [[1,0,0],[0,0,1],[0,1,0]] has det −1 (reflection). Instead rotate:
#   X=−u, Y=w, Z=v  has det +1; we compensate by negating u at build time.
_PERM_V = [[-1.0, 0.0, 0.0, 0.0],
           [ 0.0, 0.0, 1.0, 0.0],
           [ 0.0, 1.0, 0.0, 0.0],
           [ 0.0, 0.0, 0.0, 1.0]]


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY
# ══════════════════════════════════════════════════════════════════════
def generate_3d_assembly(window, panes, tenant_id=None, fmt='glb', z_up=False) -> bytes:
    fmt = fmt.lower()
    from .frame_assembly import build_members, resolve_profiles

    profiles = resolve_profiles(tenant_id,
                                getattr(window, 'material', 'Aluminium'),
                                window=window)
    _apply_window_overrides(profiles, window, tenant_id)

    # ── DIAGNOSTIC: log exactly what each role resolves to ────────────
    try:
        diag = []
        for role in ('head', 'cill', 'jamb', 'mullion', 'transom', 'sash'):
            p = profiles.get(role)
            has = bool(p.get('loops'))
            diag.append(f"{role}={p.get('code')}({'DXF' if has else 'BOX'})")
        logger.info('3D assembly [win=%s sys=%s]: %s',
                    getattr(window, 'id', '?'),
                    getattr(window, 'profile_system_id', None),
                    ' '.join(diag))
    except Exception:
        pass

    asm = build_members(window, panes, profiles)
    if not asm.members:
        raise RuntimeError('member graph: no members')

    real = prepare_sections(asm, profiles)
    logger.info('3D assembly: %d/%d members have real DXF sections',
                real, len(asm.members))

    if fmt == 'step':
        return _build_step(window, asm, z_up=z_up)
    return _build_trimesh(window, asm, fmt)


def prepare_sections(asm, profiles) -> int:
    """
    SINGLE SOURCE OF TRUTH for member cross-sections.

    For every member, normalise its profile once via _section_rings():
      * dedupe / auto-rotate (u = bar, v = through-wall depth) / origin at 0
      * depth-clamp shallow sections to _MIN_DEPTH by scaling v
    and stamp the results on the member:
        m._rings    normalised rings  (rings[0] outer, rings[1:] holes)
        m._sec_bar  actual section bar width  (mm)
        m._sec_dep  actual section depth      (mm)
        m._has_dxf  True when backed by a traced DXF (else rectangle)
    ALL back-ends (trimesh GLB/STL, cadquery STEP, FreeCAD) consume these —
    fixing geometry here fixes every export identically.

    Returns the number of members backed by real DXF loops.
    """
    real = 0
    cache: dict = {}
    for m in asm.members:
        prof  = profiles.get(m.role)
        loops = prof.get('loops')
        key = (f"{m.profile_code or m.role}:"
               f"{m.bar_width:.1f}x{m.depth:.1f}:{'L' if loops else 'R'}")
        if key not in cache:
            rings, sb, sd = _section_rings(loops, m.bar_width, m.depth)
            if sd < _MIN_DEPTH and sd > 0:
                sy = _MIN_DEPTH / sd
                rings = [[(u, v * sy) for u, v in r] for r in rings]
                sd = _MIN_DEPTH
            cache[key] = (rings, sb, sd)
        rings, sb, sd = cache[key]
        m._rings   = rings
        m._sec_bar = sb
        m._sec_dep = sd
        m._has_dxf = bool(loops)
        m.depth    = sd            # keep member metadata consistent
        if loops:
            real += 1
    return real


# ══════════════════════════════════════════════════════════════════════
#  PER-WINDOW PROFILE OVERRIDES  (design_json.profileRoles)
# ══════════════════════════════════════════════════════════════════════
def _apply_window_overrides(profiles, window, tenant_id):
    """
    design_json.profileRoles = { "head": "HF-90", "cill": "SF-165", ... }
    Set from the editor PROFILES tab → "Use for this window".
    """
    import json as _json
    try:
        design    = _json.loads(getattr(window, 'design_json', None) or '{}')
        overrides = design.get('profileRoles', {})
        if not overrides or not tenant_id:
            return
        from ..models.cad_profile import CadProfile
        for role, code in overrides.items():
            if not code:
                continue
            p = CadProfile.query.filter_by(
                    tenant_id=tenant_id, code=code, is_active=True).first()
            if not p:
                continue
            loops = None
            if p.geometry_json:
                try:
                    loops = _json.loads(p.geometry_json)
                except Exception:
                    loops = None
            profiles.by_role[role] = {
                'code':         p.code,
                'bar':          float(p.bar_width_mm),
                'depth':        float(p.depth_mm),
                'glass_rebate': float(p.glass_rebate_mm or 20.0),
                'loops':        loops,
            }
    except Exception as exc:
        logger.debug('_apply_window_overrides skipped: %s', exc)


# ══════════════════════════════════════════════════════════════════════
#  CROSS-SECTION  (pure Python — no shapely dependency)
# ══════════════════════════════════════════════════════════════════════
def _ring_area(r):
    s = 0.0
    for i in range(len(r)):
        x1, y1 = r[i]; x2, y2 = r[(i + 1) % len(r)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _section_rings(loops, bar: float, depth: float):
    """
    Return (rings, sec_bar, sec_depth) where rings is a list of point-lists:
      rings[0]  = outer boundary (largest area)
      rings[1:] = chamber holes
    Each point is (u, v): u across the bar (0..sec_bar), v through the wall.

    Pure Python — works with or without shapely. Auto-rotates the traced
    section 90° when it is drawn depth-along-X. Falls back to a plain
    rectangle ring when there are no usable loops.
    """
    rect = ([[(0.0, 0.0), (bar, 0.0), (bar, depth), (0.0, depth)]],
            float(bar), float(depth))
    if not loops:
        return rect

    rings = []
    for lp in loops:
        pts = [(float(x), float(y)) for x, y in lp]
        # drop duplicate closing point if present
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 3:
            rings.append(pts)
    if not rings:
        return rect

    rings.sort(key=_ring_area, reverse=True)

    # bounding box of the outer ring
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w, h = maxx - minx, maxy - miny

    # rotate 90° if drawn depth-along-X (swap so u=bar, v=depth)
    rotate = abs(w - bar) + abs(h - depth) > abs(h - bar) + abs(w - depth)

    def _xf(pt):
        x, y = pt
        if rotate:
            x, y = y, x           # 90° swap
        return (x, y)

    rings = [[_xf(p) for p in r] for r in rings]
    # recompute bounds after rotation, translate to origin
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    rings = [[(x - minx, y - miny) for x, y in r] for r in rings]
    return rings, float(maxx - minx), float(maxy - miny)


def _prism(trimesh, np, rings, length):
    """
    Extrude a 2D polygon (outer ring + holes) along +Z by `length`,
    using mapbox_earcut for the caps — no shapely needed.
    Returns a watertight Trimesh, or None on failure.
    """
    try:
        import mapbox_earcut as _em  # type: ignore[import]
    except Exception:
        _em = None

    if _em is not None:
        try:
            arr = [np.asarray(r, dtype=np.float64) for r in rings if len(r) >= 3]
            verts2d = np.concatenate(arr, axis=0)
            ring_ends = np.cumsum([len(r) for r in arr]).astype(np.uint32)
            tris = _em.triangulate_float64(verts2d, ring_ends).reshape(-1, 3)
            n = len(verts2d)
            v3 = np.vstack([
                np.column_stack([verts2d, np.zeros(n)]),
                np.column_stack([verts2d, np.full(n, length)]),
            ])
            faces = []
            for t in tris:
                faces.append([t[0], t[2], t[1]])            # bottom cap
                faces.append([t[0] + n, t[1] + n, t[2] + n])  # top cap
            base = 0
            for r in arr:
                m = len(r)
                for i in range(m):
                    a = base + i; b = base + (i + 1) % m
                    faces.append([a, b, b + n])
                    faces.append([a, b + n, a + n])
                base += m
            mesh = trimesh.Trimesh(vertices=v3, faces=np.array(faces),
                                    process=True)
            if len(mesh.faces) > 0:
                return mesh
        except Exception as exc:
            logger.debug('earcut prism failed (%s) — box fallback', exc)

    # last-resort: bounding box
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    bx = max(xs) - min(xs); by = max(ys) - min(ys)
    box = trimesh.creation.box(extents=[bx, by, length])
    box.apply_translation([bx / 2 + min(xs), by / 2 + min(ys), length / 2])
    return box


#  TRIMESH BACK-END  (GLB / STL)
# ══════════════════════════════════════════════════════════════════════
def _build_trimesh(window, asm, fmt: str) -> bytes:
    import trimesh
    import numpy as np

    W  = float(window.width_mm)
    H  = float(window.height_mm)
    cx = W / 2.0
    cy = H / 2.0
    fr, fg, fb = _frame_rgb(getattr(window, 'frame_colour_hex', '#6a6a6c'))
    frame_col  = [int(fr * 255), int(fg * 255), int(fb * 255), 255]

    # ── Depth stacking — measured from the PWQ-3645 reference DWG ─────
    # Plan section (jamb 60×90 at Y[1065..1155], sash 60×58 at Y[1065..1123]):
    #   * The FRAME fills the full wall depth  (Z 0 → frame_depth).
    #   * The SASH is FLUSH WITH THE FRAME AT THE EXTERNAL FACE (Z = 0) and
    #     only `sash_depth` deep — the remaining internal frame depth forms
    #     the rebate upstand behind it.
    #   * Glass/beads sit within the sash depth band.
    # External face = Z 0 in our build (members rest on Z=0 already), so the
    # sash needs NO z offset; the previous forward-nesting was inverted.
    frame_depth = max((m.depth for m in asm.members
                       if m.role in ('head', 'cill', 'jamb', 'outer_frame',
                                     'threshold')), default=_MIN_DEPTH)
    sash_depth  = max((m.depth for m in asm.members
                       if m.role in ('sash', 'door_leaf')), default=0.0)

    frame_meshes = []
    for m in asm.members:
        mesh = _member_mesh(trimesh, np, m,
                            m._rings, m._sec_bar, m._sec_dep, cx, cy)
        if mesh is not None and len(mesh.faces) > 0:
            frame_meshes.append(mesh)

    if not frame_meshes:
        raise RuntimeError('no frame meshes built')

    frame = trimesh.util.concatenate(frame_meshes)
    frame.visual.face_colors = frame_col
    meshes = [frame]

    # Reference depth = the FRAME face depth (head/jamb), NOT the sill — the
    # sill is much deeper (165mm) and would push the glass far behind the frame.
    frame_ref = max((m.depth for m in asm.members
                     if m.role in ('head', 'jamb', 'mullion', 'transom',
                                   'sash', 'outer_frame')), default=_MIN_DEPTH)
    dep_max = max((m.depth for m in asm.members), default=_MIN_DEPTH)
    # Glass sits in the rebate pocket, ~24 mm behind the frame's internal face.
    glass_z = max(frame_ref - 24.0, frame_ref * 0.35)
    for g in asm.glass:
        gx = g.x + g.w / 2.0 - cx
        gy = g.y + g.h / 2.0 - cy
        if g.infill == 'panel':
            gm = trimesh.creation.box(
                extents=[max(g.w, 1), max(g.h, 1), g.thickness])
            gm.apply_translation([gx, gy, frame_ref * 0.5])
            gm.visual.face_colors = frame_col
        else:
            gm = trimesh.creation.box(extents=[max(g.w, 1), max(g.h, 1), 8.0])
            gm.apply_translation([gx, gy, glass_z])
            gm.visual.face_colors = list(_GLASS_RGBA)
        meshes.append(gm)

    if fmt == 'glb':
        return trimesh.Scene(meshes).export(file_type='glb')
    if fmt == 'stl':
        return trimesh.util.concatenate(meshes).export(file_type='stl')
    raise ValueError(f'unsupported fmt: {fmt}')


def _member_mesh(trimesh, np, m, rings, sec_bar: float, sec_dep: float,
                 cx: float, cy: float):
    """
    Build one member: extrude the section rings along +Z by the member
    length (via earcut, no shapely), then apply ONE axis-permutation matrix
    (det=+1, pure rotation) to map it into world space, then translate.

    NO chained rotations. NO boolean cuts. Butt joints only.
    """
    L = m.length
    if L < 1:
        return None

    # 1. Extrude — rings live in XY (X=u bar, Y=v depth), prism along +Z=L
    solid = _prism(trimesh, np, rings, L)
    if solid is None:
        return None
    # solid spans: u ∈ [0, sec_bar], v ∈ [0, sec_dep], w ∈ [0, L]

    horizontal = abs(m.y2 - m.y1) < 0.5
    if horizontal:
        # (u,v,w) → (X=w, Y=u, Z=v)
        solid.apply_transform(np.array(_PERM_H))
        x0 = min(m.x1, m.x2) - cx
        y0 = (m.y1 - cy) - sec_bar / 2.0
        b  = solid.bounds
        solid.apply_translation([x0 - b[0][0], y0 - b[0][1], -b[0][2]])
    else:
        # (u,v,w) → (X=−u, Y=w, Z=v)   [negated u keeps det = +1]
        solid.apply_transform(np.array(_PERM_V))
        y0 = min(m.y1, m.y2) - cy
        x0 = (m.x1 - cx) - sec_bar / 2.0
        b  = solid.bounds
        solid.apply_translation([x0 - b[0][0], y0 - b[0][1], -b[0][2]])

    return solid


# ══════════════════════════════════════════════════════════════════════
#  CADQUERY BACK-END  (STEP)
# ══════════════════════════════════════════════════════════════════════
def _build_step(window, asm, z_up: bool = False) -> bytes:
    try:
        import cadquery as cq
    except ImportError:
        raise RuntimeError('STEP requires cadquery (OCP kernel).')

    W  = float(window.width_mm); H = float(window.height_mm)
    cx = W / 2.0; cy = H / 2.0
    r, g, b = _frame_rgb(getattr(window, 'frame_colour_hex', '#6a6a6c'))

    a = cq.Assembly()
    idx = 0

    def _zup(s):
        # Rotate 90° about X: world Y (height) → Z, world Z (depth) → -Y.
        # Converts this app's native X=width/Y=height/Z=depth convention to
        # the common Z-up convention some BIM/CAM tools expect.
        return s.rotate((0, 0, 0), (1, 0, 0), 90) if z_up else s

    for m in asm.members:
        rings, sec_bar, sec_dep = m._rings, m._sec_bar, m._sec_dep
        try:
            s = _member_solid_cq(cq, m, rings, sec_bar, sec_dep, cx, cy)
        except Exception as exc:
            logger.warning('cq member %s profile failed (%s) — box fallback',
                           m.id, exc)
            s = None
        if s is None:
            # Bulletproof box fallback so the member is never missing.
            try:
                L = m.length
                if abs(m.y2 - m.y1) < 0.5:   # horizontal
                    x0 = min(m.x1, m.x2) - cx
                    s = (cq.Workplane('XY')
                         .box(L, sec_bar, sec_dep, centered=False)
                         .translate((x0, (m.y1 - cy) - sec_bar/2.0, 0)))
                else:                          # vertical
                    y0 = min(m.y1, m.y2) - cy
                    s = (cq.Workplane('XY')
                         .box(sec_bar, L, sec_dep, centered=False)
                         .translate(((m.x1 - cx) - sec_bar/2.0, y0, 0)))
            except Exception as exc2:
                logger.warning('cq member %s box fallback failed: %s', m.id, exc2)
                s = None
        if s is not None:
            idx += 1
            a.add(_zup(s), name=f'{m.role}_{m.id}', color=cq.Color(r, g, b))

    if idx == 0:
        raise RuntimeError('no frame solids built')

    dep_max = max((mm.depth for mm in asm.members), default=_MIN_DEPTH)
    glass_z = max(dep_max - 24.0, dep_max * 0.35)
    for i, gc in enumerate(asm.glass):
        gx = gc.x + gc.w / 2.0 - cx
        gy = gc.y + gc.h / 2.0 - cy
        if gc.infill == 'panel':
            s = cq.Workplane('XY').box(gc.w, gc.h, gc.thickness)\
                  .translate((gx, gy, dep_max * 0.5))
            a.add(_zup(s), name=f'panel_{i+1}', color=cq.Color(r, g, b))
        else:
            s = cq.Workplane('XY').box(gc.w, gc.h, 8.0)\
                  .translate((gx, gy, glass_z + 4.0))
            a.add(_zup(s), name=f'glass_{i+1}',
                  color=cq.Color(0.55, 0.75, 0.80, 0.35))

    with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tf:
        path = tf.name
    try:
        a.export(path)
        with open(path, 'rb') as f:
            return f.read()
    finally:
        _rm(path)


def _dedupe(points, tol=1e-4):
    """Remove consecutive duplicate / sub-tolerance points that make cadquery's
    makeLine fail with 'BRep_API: command not done' (zero-length edges).
    Also drops a trailing point equal to the first (polyline .close() re-adds it)."""
    out = []
    for p in points:
        if not out:
            out.append(p)
            continue
        dx = p[0] - out[-1][0]
        dy = p[1] - out[-1][1]
        if (dx * dx + dy * dy) > (tol * tol):
            out.append(p)
    if len(out) >= 2:
        dx = out[0][0] - out[-1][0]
        dy = out[0][1] - out[-1][1]
        if (dx * dx + dy * dy) <= (tol * tol):
            out.pop()
    return out


def _simplify_ring(points, min_seg=0.3, collinear_tol=1e-3):
    """
    Clean a dense/noisy traced outline so cadquery builds it reliably in any
    orientation:
      1. dedupe exact/near-duplicate points
      2. drop points closer than `min_seg` mm to the previous kept point
      3. drop points that are nearly collinear with their neighbours
    Keeps the shape faithful while removing the sub-0.5mm segment noise that
    made OCCT's edge builder fail on horizontal members.
    """
    pts = _dedupe(points)
    if len(pts) < 4:
        return pts

    # 2. minimum segment length
    kept = [pts[0]]
    for p in pts[1:]:
        dx = p[0] - kept[-1][0]; dy = p[1] - kept[-1][1]
        if (dx * dx + dy * dy) >= (min_seg * min_seg):
            kept.append(p)
    if len(kept) < 4:
        return _dedupe(points)   # too aggressive — fall back to just dedupe

    # 3. collinear removal (cross-product area of consecutive triples ~ 0)
    out = []
    n = len(kept)
    for i in range(n):
        a = kept[(i - 1) % n]; b = kept[i]; c = kept[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > collinear_tol:
            out.append(b)
    return out if len(out) >= 3 else kept


def _member_solid_cq(cq, m, rings, sec_bar: float, sec_dep: float,
                     cx: float, cy: float):
    """
    cadquery member — built the SAME way as the working trimesh/FreeCAD paths:
    profile in the XY plane → extrude +Z by length → rotate into world
    orientation → translate into place. This avoids the arbitrary-Workplane
    polyline construction that failed for horizontal members (transom).

    Local profile: u = X (across bar, 0..sec_bar), v = Y (through depth),
    extruded +Z by member length L.
    """
    L = m.length
    if L < 1:
        return None
    horizontal = abs(m.y2 - m.y1) < 0.5

    outer = _simplify_ring([(float(x), float(y)) for x, y in rings[0]])
    holes = [_simplify_ring([(float(x), float(y)) for x, y in r])
             for r in rings[1:]]
    holes = [h for h in holes if len(h) >= 3]
    if len(outer) < 3:
        return None

    # 1. profile in XY, extrude +Z by L
    wp = cq.Workplane('XY').polyline(outer).close().extrude(L)
    for hole in holes:
        try:
            hw = cq.Workplane('XY').polyline(hole).close().extrude(L)
            wp = wp.cut(hw)
        except Exception:
            pass  # skip a bad chamber rather than fail the whole member

    # after extrude: X∈[0,sec_bar] (u), Y∈[0,sec_dep] (v), Z∈[0,L] (length)

    # 2. rotate length axis (Z) into the member direction (keep Workplane type)
    if horizontal:
        wp = wp.rotate((0, 0, 0), (0, 1, 0), 90)     # Z → X
        x0 = min(m.x1, m.x2) - cx
        yC = m.y1 - cy
        bb = wp.val().BoundingBox()
        wp = wp.translate((
            x0 - bb.xmin,
            yC - (bb.ymin + bb.ymax) / 2.0,
            -bb.zmin,
        ))
    else:
        wp = wp.rotate((0, 0, 0), (1, 0, 0), -90)    # Z → Y
        y0 = min(m.y1, m.y2) - cy
        xC = m.x1 - cx
        bb = wp.val().BoundingBox()
        wp = wp.translate((
            xC - (bb.xmin + bb.xmax) / 2.0,
            y0 - bb.ymin,
            -bb.zmin,
        ))
    return wp




# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════
def _frame_rgb(hex_colour: str):
    try:
        h = (hex_colour or '#6a6a6c').lstrip('#')
        return (int(h[0:2], 16) / 255,
                int(h[2:4], 16) / 255,
                int(h[4:6], 16) / 255)
    except Exception:
        return 0.42, 0.42, 0.44


def _rm(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass