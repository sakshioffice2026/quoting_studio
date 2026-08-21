"""
app/services/orthographic_dxf.py — true orthographic multiview DXF
(front elevation + top plan + side view) generated from the STEP solid
via headless FreeCAD (freecadcmd, Part.projectEx — no Gui needed) and
written out as a real DXF using ezdxf.
"""
from __future__ import annotations
import os, json, subprocess, tempfile, logging

from .model3d_freecad import _find_freecad, _read

logger = logging.getLogger(__name__)

L_VIS = 'PROF_OUTLINE'
L_HID = 'HIDDEN_LINE'
L_ANNOT = 'DIM_ANNOTATION'

VIEW_GAP = 150  # mm gap between views on sheet


def generate_orthographic_dxf(window, panes, tenant_id=None) -> bytes:
    import ezdxf
    from .dxf_layers import setup_layers, setup_text_styles

    freecad = _find_freecad()
    if not freecad:
        raise RuntimeError('FreeCAD not found — tried all known paths')

    from .model3d_freecad import generate_3d_freecad
    step_bytes = generate_3d_freecad(window, panes, tenant_id=tenant_id, fmt='step')
    if not step_bytes:
        raise RuntimeError('STEP generation failed — cannot build orthographic views')

    tmp_dir = None
    for d in ('E:\\', 'D:\\', 'C:\\'):
        if os.path.isdir(d):
            candidate = os.path.join(d, 'qs_freecad_tmp')
            try:
                os.makedirs(candidate, exist_ok=True)
                testfile = os.path.join(candidate, '.wtest')
                with open(testfile, 'wb') as tf:
                    tf.write(b'x')
                os.remove(testfile)
                tmp_dir = candidate
                break
            except Exception:
                continue
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    wid = getattr(window, 'id', 0)

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

        r = subprocess.run([freecad, script_path],
                           capture_output=True, text=True,
                           timeout=180, env=env)
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
    out = []
    for p in pts:
        if view == "front":
            out.append((p.x, p.y))
        elif view == "top":
            out.append((p.x, p.z))
        else:  # side
            out.append((p.z, p.y))
    return out

doc = App.newDocument("QS_Ortho")
Import.insert(r"{spath}", doc.Name)
doc.recompute()

shapes = [o.Shape for o in doc.Objects if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
result = {{}}

if not shapes:
    print("ERROR: no shapes imported from STEP", flush=True)
else:
    directions = ["front", "top", "side"]
    for view in directions:
        vis_edges = []
        for shp in shapes:
            for e in shp.Edges:
                pts = e.discretize(Deflection=0.15)
                if len(pts) >= 2:
                    vis_edges.append(project_pts(pts, view))
        result[view] = {{"visible": vis_edges, "hidden": []}}
        print(f"{{view}}: {{len(vis_edges)}} edges", flush=True)

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
    return w, h


def _write_dxf(views, window) -> bytes:
    import ezdxf, io
    from .dxf_layers import setup_layers, setup_text_styles

    doc = ezdxf.new('R2010', setup=True)
    setup_layers(doc)
    setup_text_styles(doc)
    doc.layers.add(L_HID, dxfattribs={'color': 1})
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[0.6, 0.3, -0.3])

    msp = doc.modelspace()

    front = views.get('front', {'visible': [], 'hidden': []})
    top   = views.get('top',   {'visible': [], 'hidden': []})
    side  = views.get('side',  {'visible': [], 'hidden': []})

    fw, fh = _draw_view(msp, front, 0, 0, 'FRONT (ELEVATION)')
    _draw_view(msp, top,   0, fh + VIEW_GAP, 'TOP (PLAN)')
    _draw_view(msp, side,  fw + VIEW_GAP, 0, 'SIDE VIEW')

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')