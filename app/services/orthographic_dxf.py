"""
app/services/orthographic_dxf.py — true orthographic multiview DXF
(front elevation + top plan + side view) generated from the STEP solid
via headless FreeCAD (freecadcmd, Part.projectEx — no Gui needed) and
written out as a real DXF using ezdxf.
"""
from __future__ import annotations
import os, json, subprocess, tempfile, logging, hashlib, time, threading

from .model3d_freecad import _find_freecad, _read

logger = logging.getLogger(__name__)

L_VIS = 'PROF_OUTLINE'
L_HID = 'HIDDEN_LINE'
L_ANNOT = 'DIM_ANNOTATION'
L_DIM = 'DIMENSIONS'

VIEW_GAP = 150  # mm gap between views on sheet


_STEP_CACHE = {}
_VIEWS_CACHE = {}  # cache_key -> parsed {front, top, side} view dict (skips FreeCAD subprocess entirely)

_DISK_CACHE_TTL = 1800  # seconds

_KEY_LOCKS = {}
_KEY_LOCKS_GUARD = threading.Lock()


def _lock_for(cache_key: str) -> threading.Lock:
    """One lock per cache_key so concurrent requests for the SAME window
    coalesce into a single FreeCAD subprocess run (the second/third request
    just waits, then reads the cache the first one filled) instead of each
    launching its own FreeCAD process and thrashing the machine. Different
    windows still run fully in parallel."""
    with _KEY_LOCKS_GUARD:
        lock = _KEY_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[cache_key] = lock
        return lock


def _disk_cache_path(cache_key: str) -> str:
    h = hashlib.sha1(cache_key.encode('utf-8')).hexdigest()
    return os.path.join(tempfile.gettempdir(), f'qs_ortho_views_{h}.json')


def _disk_cache_get(cache_key: str):
    """Cross-process cache: orthographic.dxf and engineering.dxf are served
    by separate HTTP requests that may land on different worker processes,
    so the in-memory _VIEWS_CACHE alone doesn't dedupe the FreeCAD subprocess
    across them. A small on-disk cache lets any worker reuse a projection
    another worker just computed for the same window/pane layout."""
    path = _disk_cache_path(cache_key)
    try:
        if time.time() - os.path.getmtime(path) > _DISK_CACHE_TTL:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _disk_cache_set(cache_key: str, views: dict) -> None:
    path = _disk_cache_path(cache_key)
    try:
        tmp = path + f'.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(views, f)
        os.replace(tmp, path)
    except Exception:
        logger.debug('Could not write disk views cache %s', path, exc_info=True)


def get_step_views(window, panes, tenant_id=None) -> dict:
    """
    Single source of truth for 2D geometry: generates the STEP solid for
    this window/pane configuration first, then projects it (via headless
    FreeCAD) into front/top/side edge sets.

    Every consumer that needs a circular-window elevation (orthographic
    views, the engineering drawing sheet, the advanced parametric DXF)
    must call this instead of recomputing circle/arc geometry independently,
    so downstream drawings can never drift from the STEP file.

    Returns {'front'|'top'|'side': {'visible': [...], 'hidden': [...],
    'frame': [...], 'glass': {label: [edges...]}}}.
    """
    from .model3d import generate_3d
    # Cache STEP generation to avoid regenerating for same window
    wid = getattr(window, 'id', 0)
    cache_key = f"{wid}_{hash(str([(p.x_norm, p.y_norm, p.w_norm, p.h_norm, p.opener_type) for p in panes]))}"

    # Fast path: identical window/panes already projected before — skip both
    # STEP (re)generation and the FreeCAD subprocess launch entirely. The
    # FreeCAD subprocess start-up + projection pass is the dominant cost of
    # this endpoint, so this is the single biggest win for repeat exports.
    if cache_key in _VIEWS_CACHE:
        logger.debug('Using cached orthographic views for window=%s', wid)
        return _VIEWS_CACHE[cache_key]

    disk_views = _disk_cache_get(cache_key)
    if disk_views is not None:
        logger.debug('Using disk-cached orthographic views for window=%s', wid)
        _VIEWS_CACHE[cache_key] = disk_views
        return disk_views

    # Serialize concurrent requests for the SAME window: without this,
    # simultaneous requests to /3d, /orthographic.dxf and /engineering.dxf
    # for one window each launch their own FreeCAD subprocess in parallel,
    # which can thrash a modest machine badly enough to look hung. The
    # first request through the lock does the real work; the rest wait
    # and then hit the cache above.
    lock = _lock_for(cache_key)
    with lock:
        if cache_key in _VIEWS_CACHE:
            return _VIEWS_CACHE[cache_key]
        disk_views = _disk_cache_get(cache_key)
        if disk_views is not None:
            _VIEWS_CACHE[cache_key] = disk_views
            return disk_views

        views = _compute_step_views(window, panes, tenant_id, wid, cache_key)

    _KEY_LOCKS_GUARD.acquire()
    try:
        _KEY_LOCKS.pop(cache_key, None)
    finally:
        _KEY_LOCKS_GUARD.release()

    return views


def _compute_step_views(window, panes, tenant_id, wid, cache_key) -> dict:
    from .model3d import generate_3d

    freecad = _find_freecad()
    if not freecad:
        raise RuntimeError('FreeCAD not found — tried all known paths')

    if cache_key in _STEP_CACHE:
        step_bytes = _STEP_CACHE[cache_key]
        logger.debug('Using cached STEP for window=%s', wid)
    else:
        # Same fix as techdraw_export.py: use the curve-aware STEP builder so the
        # orthographic views match the actual frame shape instead of always
        # being rectangular.
        step_bytes = generate_3d(window, panes, tenant_id=tenant_id, fmt='step')
        if not step_bytes:
            raise RuntimeError('STEP generation failed — cannot build orthographic views')
        # Cache for 30 minutes max
        _STEP_CACHE[cache_key] = step_bytes
        if len(_STEP_CACHE) > 50:
            _STEP_CACHE.pop(next(iter(_STEP_CACHE)))

    tmp_dir = tempfile.gettempdir()  # OPTIMIZED: skip drive search

    step_path   = os.path.join(tmp_dir, f'qs_ortho_in_{wid}.step')
    script_path = os.path.join(tmp_dir, f'qs_ortho_{wid}.py')
    out_path    = os.path.join(tmp_dir, f'qs_ortho_out_{wid}.json')

    try:
        with open(step_path, 'wb') as f:
            f.write(step_bytes)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(_build_script(step_path, out_path))

        env = os.environ.copy()
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        env['QT_QPA_PLATFORM'] = 'offscreen'

        r = subprocess.run([freecad, script_path],
                           capture_output=True, text=True,
                           timeout=120, env=env)
        logger.debug('FreeCAD ortho stdout: %s', (r.stdout or '')[-2000:])
        if r.stderr:
            logger.warning('FreeCAD ortho stderr: %s', r.stderr[-1000:])

        if 'ORTHO_DONE' not in (r.stdout or ''):
            raise RuntimeError(
                f'FreeCAD orthographic script did not complete. '
                f'stdout: {(r.stdout or "")[-1000:]} '
                f'stderr: {(r.stderr or "")[-1000:]}')

        views = json.loads(_read(out_path).decode('utf-8'))

    finally:
        for p in (step_path, script_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    _VIEWS_CACHE[cache_key] = views
    if len(_VIEWS_CACHE) > 50:
        _VIEWS_CACHE.pop(next(iter(_VIEWS_CACHE)))
    _disk_cache_set(cache_key, views)

    return views


def generate_orthographic_dxf(window, panes, tenant_id=None) -> bytes:
    views = get_step_views(window, panes, tenant_id=tenant_id)
    return _write_dxf(views, window)


def _build_script(step_path: str, out_path: str) -> str:
    spath = step_path.replace('\\', '/')
    opath = out_path.replace('\\', '/')

    return f'''
import FreeCAD as App
import Import, json

def project_pts(pts, view):
    """Plain orthographic projection (no hidden-line removal — every edge
    of every solid is drawn). This trades hidden/visible distinction for
    guaranteed completeness: HLR/outline APIs (Part.HLRBRep, projectEx,
    findShapeOutline) either don't exist across FreeCAD versions or only
    return the outer silhouette, silently dropping interior mullion/sash/
    bead lines — which is what caused the earlier near-empty drawings."""
    LIMIT = 1e6  # anything beyond this is FreeCAD's degenerate/invalid sentinel
    out = []
    for p in pts:
        if view == "front":
            x, y = p.x, p.y
        elif view == "top":
            x, y = p.x, p.z
        else:  # side
            x, y = p.z, p.y
        if abs(x) > LIMIT or abs(y) > LIMIT or x != x or y != y:  # x!=x -> NaN
            return []  # degenerate edge: drop the whole edge, not just the point
        out.append((x, y))
    return out

doc = App.newDocument("QS_Ortho")
Import.insert(r"{spath}", doc.Name)
doc.recompute()

objs = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
result = {{}}

if not objs:
    print("ERROR: no shapes imported from STEP", flush=True)
else:
    directions = ["front", "top", "side"]
    vis_edges = {{v: [] for v in directions}}
    frame_edges = {{v: [] for v in directions}}
    glass_edges = {{v: {{}} for v in directions}}
    dropped = {{v: 0 for v in directions}}

    # Discretize each edge ONCE (this is the expensive tessellation call),
    # then reuse the same 3D points for all three view projections instead
    # of re-discretizing per view. This is a ~3x speedup on the projection
    # pass for models with many edges (mullions/sashes/beads).
    for o in objs:
        label = (o.Label or o.Name or "").lower()
        is_glass = label.startswith("glass")
        for e in o.Shape.Edges:
            try:
                pts = e.discretize(Deflection=0.15)
            except Exception:
                for v in directions:
                    dropped[v] += 1
                continue
            if len(pts) < 2:
                for v in directions:
                    dropped[v] += 1
                continue
            for view in directions:
                proj = project_pts(pts, view)
                if len(proj) >= 2:
                    vis_edges[view].append(proj)
                    if is_glass:
                        glass_edges[view].setdefault(label, []).append(proj)
                    else:
                        frame_edges[view].append(proj)
                else:
                    dropped[view] += 1

    for view in directions:
        result[view] = {{
            "visible": vis_edges[view], "hidden": [],
            "frame": frame_edges[view], "glass": glass_edges[view],
        }}
        print(f"{{view}}: {{len(vis_edges[view])}} edges, {{dropped[view]}} degenerate edges dropped", flush=True)

with open(r"{opath}", "w", encoding="utf-8") as f:
    json.dump(result, f)

App.closeDocument(doc.Name)
print("ORTHO_DONE", flush=True)
'''


def _bbox(edges):
    xs, ys = [], []
    for e in edges:
        for x, y in e:
            xs.append(x)
            ys.append(y)
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _draw_view(msp, view, ox, oy, label):
    import ezdxf
    vis = view.get('visible', [])
    hid = view.get('hidden', [])
    x0, y0, x1, y1 = _bbox(vis + hid)

    for edge in vis:
        pts = [(px - x0 + ox, py - y0 + oy) for px, py in edge]
        if len(pts) >= 2:
            msp.add_lwpolyline(pts, dxfattribs={'layer': L_VIS})

    for edge in hid:
        pts = [(px - x0 + ox, py - y0 + oy) for px, py in edge]
        if len(pts) >= 2:
            msp.add_lwpolyline(
                pts, dxfattribs={'layer': L_HID, 'linetype': 'DASHED'})

    w, h = x1 - x0, y1 - y0
    t = msp.add_text(label, dxfattribs={'layer': L_ANNOT, 'height': 20})
    t.set_placement((ox, oy - 30), align=ezdxf.enums.TextEntityAlignment.LEFT)

    # overall width (below) and height (right) dimensions
    if w > 0:
        dim_w = msp.add_linear_dim(
            base=(ox, oy - 80), p1=(ox, oy), p2=(ox + w, oy),
            dimstyle='ENGINEERING', dxfattribs={'layer': L_DIM})
        dim_w.render()
    if h > 0:
        dim_h = msp.add_linear_dim(
            base=(ox + w + 80, oy), p1=(ox + w, oy), p2=(ox + w, oy + h),
            angle=90, dimstyle='ENGINEERING', dxfattribs={'layer': L_DIM})
        dim_h.render()

    return w, h


def _write_dxf(views, window) -> bytes:
    import ezdxf, io
    from .dxf_layers import setup_layers, setup_text_styles, setup_dimstyle

    doc = ezdxf.new('R2010', setup=True)
    setup_layers(doc)
    setup_text_styles(doc)
    setup_dimstyle(doc)
    doc.layers.add(L_HID, dxfattribs={'color': 1})
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[0.6, 0.3, -0.3])

    msp = doc.modelspace()

    front = views.get('front', {'visible': [], 'hidden': []})
    top   = views.get('top',   {'visible': [], 'hidden': []})
    side  = views.get('side',  {'visible': [], 'hidden': []})

    for name, v in (('front', front), ('top', top), ('side', side)):
        if not v.get('visible') and not v.get('hidden'):
            raise RuntimeError(
                f'Orthographic "{name}" view has no valid geometry after '
                f'filtering degenerate edges — STEP solid may be corrupt.')

    fw, fh = _draw_view(msp, front, 0, 0, 'FRONT (ELEVATION)')
    _draw_view(msp, top,   0, fh + VIEW_GAP, 'TOP (PLAN)')
    _draw_view(msp, side,  fw + VIEW_GAP, 0, 'SIDE VIEW')

    # Cross-check: the FRONT view is projected straight from the STEP
    # solid, so its bounding box should match the quoted window.width_mm /
    # height_mm. If it doesn't, the STEP geometry has drifted from the
    # stored size — flag it loudly instead of silently shipping a drawing
    # whose dimension lines don't match the quote.
    tol = 1.0  # mm
    quoted_w = float(getattr(window, 'width_mm', 0) or 0)
    quoted_h = float(getattr(window, 'height_mm', 0) or 0)
    if quoted_w and abs(fw - quoted_w) > tol:
        logger.warning(
            'Orthographic FRONT view width %.2fmm does not match quoted '
            'window.width_mm %.2fmm (window id=%s) — STEP geometry may '
            'have drifted from the stored dimension.',
            fw, quoted_w, getattr(window, 'id', '?'))
        _add_text_note(
            msp, f'DIMENSION MISMATCH: drawing width {fw:.0f}mm '
                 f'vs quoted {quoted_w:.0f}mm', 0, -60)
    if quoted_h and abs(fh - quoted_h) > tol:
        logger.warning(
            'Orthographic FRONT view height %.2fmm does not match quoted '
            'window.height_mm %.2fmm (window id=%s) — STEP geometry may '
            'have drifted from the stored dimension.',
            fh, quoted_h, getattr(window, 'id', '?'))
        _add_text_note(
            msp, f'DIMENSION MISMATCH: drawing height {fh:.0f}mm '
                 f'vs quoted {quoted_h:.0f}mm', 0, -100)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')


def _add_text_note(msp, text, x, y):
    import ezdxf
    t = msp.add_text(text, dxfattribs={'layer': L_ANNOT, 'height': 20, 'color': 1})
    t.set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.LEFT)