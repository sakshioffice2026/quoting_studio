"""
app/services/techdraw_export.py — 2D drawing export via headless FreeCAD.

Avoids TechDrawGui.exportPageAsSvg/exportPageAsPdf entirely (that path
needs real Qt paint and breaks under any --console / freecadcmd mode).
Instead: runs fully headless under freecadcmd, projects the shape to 2D
edges with TechDraw.findShapeOutline() (App-level, no Gui needed), and
writes the SVG (elevation + section + dimensions + title block) by hand.
"""
from __future__ import annotations
import os, json, subprocess, tempfile, logging
from datetime import date

from .model3d_freecad import _find_freecad, _read

logger = logging.getLogger(__name__)


def generate_techdraw(window, panes, tenant_id=None, fmt='svg') -> bytes:
    fmt = fmt.lower()
    if fmt not in ('svg', 'pdf'):
        raise ValueError("fmt must be 'svg' or 'pdf'")

    freecad = _find_freecad()
    if not freecad:
        raise RuntimeError('FreeCAD not found — tried all known paths')

    from .model3d import generate_3d
    # Use the same curve-aware STEP builder as the /3d/step download (the one
    # that already produces the correct round/arched/gothic solid — see
    # canonical_geometry.py / model3d.py). The old model3d_freecad.py builder
    # only knows straight horizontal/vertical members, so it always produced
    # a rectangular STEP here regardless of the Designer's frame shape.
    step_bytes = generate_3d(window, panes, tenant_id=tenant_id, fmt='step')
    if not step_bytes:
        raise RuntimeError('STEP generation failed — cannot build drawing')

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

    step_path   = os.path.join(tmp_dir, f'qs_td_in_{wid}.step')
    meta_path   = os.path.join(tmp_dir, f'qs_td_meta_{wid}.json')
    script_path = os.path.join(tmp_dir, f'qs_td_{wid}.py')
    out_path    = os.path.join(tmp_dir, f'qs_td_out_{wid}.svg')

    meta = {
        'width':    float(window.width_mm),
        'height':   float(window.height_mm),
        'material': getattr(window, 'material', 'Aluminium') or 'Aluminium',
        'part_no':  f'QS-{wid}',
        'label':    getattr(window, 'label', None) or f'Window {wid}',
        'date':     date.today().strftime('%d/%m/%Y'),
        'scale':    '1:1',
    }

    try:
        with open(step_path, 'wb') as f:
            f.write(step_bytes)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(_build_script(step_path, meta_path, out_path))

        env = os.environ.copy()
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'

        r = subprocess.run([freecad, script_path],
                           capture_output=True, text=True,
                           timeout=180, env=env)
        logger.debug('FreeCAD drawing stdout: %s', (r.stdout or '')[-2000:])
        if r.stderr:
            logger.warning('FreeCAD drawing stderr: %s', r.stderr[-1000:])

        if 'TECHDRAW_DONE' not in (r.stdout or ''):
            raise RuntimeError(
                f'FreeCAD drawing script did not complete. '
                f'stdout: {(r.stdout or "")[-1000:]} '
                f'stderr: {(r.stderr or "")[-1000:]}')

        svg_bytes = _read(out_path)

        if fmt == 'svg':
            return svg_bytes
        return _svg_to_pdf(svg_bytes)

    finally:
        for p in (step_path, meta_path, script_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def _svg_to_pdf(svg_bytes: bytes) -> bytes:
    try:
        import cairosvg
        return cairosvg.svg2pdf(bytestring=svg_bytes)
    except Exception as e:
        raise RuntimeError(f'SVG->PDF conversion failed: {e}')


def _build_script(step_path: str, meta_path: str, out_path: str) -> str:
    spath = step_path.replace('\\', '/')
    mpath = meta_path.replace('\\', '/')
    opath = out_path.replace('\\', '/')

    return f'''
import FreeCAD as App
import Import, TechDraw, Part, json, math

meta = json.load(open(r"{mpath}", encoding="utf-8"))

doc = App.newDocument("QS_Draw")
Import.insert(r"{spath}", doc.Name)
doc.recompute()

shapes = [o.Shape for o in doc.Objects if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
if not shapes:
    print("ERROR: no shapes imported from STEP", flush=True)
else:
    # Plain edge projection (every edge of every solid), not
    # TechDraw.findShapeOutline() on a fused solid — findShapeOutline only
    # returns the outer silhouette and silently drops interior mullion/
    # sash/glazing-bar edges, producing near-empty drawings.
    all_edges = []
    xs, ys = [], []
    for shp in shapes:
        for e in shp.Edges:
            pts = e.discretize(Deflection=0.1)
            if len(pts) < 2:
                continue
            flat = [(p.x, p.y) for p in pts]
            all_edges.append(flat)
            xs.extend(p[0] for p in flat)
            ys.extend(p[1] for p in flat)

    margin = 40
    x_min, x_max = (min(xs), max(xs)) if xs else (0.0, 0.0)
    y_min, y_max = (min(ys), max(ys)) if ys else (0.0, 0.0)
    W = (x_max - x_min) + margin * 2
    H = (y_max - y_min) + margin * 2
    ox = -x_min + margin
    oy = y_max + margin

    def to_svg_xy(x, y):
        return (x + ox, oy - y)

    paths = []
    for flat in all_edges:
        d = "M " + " L ".join(f"{{px+ox:.2f}},{{oy-py:.2f}}" for px, py in flat)
        paths.append(f'<path d="{{d}}" stroke="black" stroke-width="0.5" fill="none"/>')

    width_mm = meta["width"]
    height_mm = meta["height"]
    dim_y = oy + 20
    dim_svg = (
        f'<line x1="{{ox:.2f}}" y1="{{dim_y:.2f}}" x2="{{ox+width_mm:.2f}}" y2="{{dim_y:.2f}}" stroke="black" stroke-width="0.3"/>'
        f'<text x="{{ox+width_mm/2:.2f}}" y="{{dim_y+12:.2f}}" font-size="10" text-anchor="middle" dominant-baseline="middle">{{width_mm:.0f}} mm</text>'
        f'<line x1="{{ox-20:.2f}}" y1="{{oy-height_mm:.2f}}" x2="{{ox-20:.2f}}" y2="{{oy:.2f}}" stroke="black" stroke-width="0.3"/>'
        f'<text x="{{ox-30:.2f}}" y="{{oy-height_mm/2:.2f}}" font-size="10" text-anchor="middle" dominant-baseline="middle" transform="rotate(-90 {{ox-30:.2f}},{{oy-height_mm/2:.2f}})">{{height_mm:.0f}} mm</text>'
    )

    title_y = H - 55
    title_height = 55
    mid_x = W / 2
    
    title_svg = (
        f'<rect x="10" y="{{title_y}}" width="{{W-20}}" height="{{title_height}}" stroke="black" stroke-width="1.5" fill="none"/>'
        f'<line x1="{{mid_x}}" y1="{{title_y}}" x2="{{mid_x}}" y2="{{H}}" stroke="black" stroke-width="1.5"/>'
        f'<line x1="10" y1="{{title_y+18}}" x2="{{W-10}}" y2="{{title_y+18}}" stroke="black" stroke-width="1"/>'
        f'<line x1="10" y1="{{title_y+36}}" x2="{{W-10}}" y2="{{title_y+36}}" stroke="black" stroke-width="1"/>'
        f'<text x="20" y="{{title_y+9}}" font-size="12" font-weight="bold" dominant-baseline="middle">ARYAMAN TECHNOLOGIES</text>'
        f'<text x="20" y="{{title_y+27}}" font-size="10" dominant-baseline="middle">Part: {{meta["part_no"]}}</text>'
        f'<text x="20" y="{{title_y+45}}" font-size="10" dominant-baseline="middle">Title: {{meta["label"]}} | Material: {{meta["material"]}} | Scale: {{meta["scale"]}} | Date: {{meta["date"]}}</text>'
        f'<text x="{{mid_x+20}}" y="{{title_y+9}}" font-size="11" font-weight="bold" dominant-baseline="middle">DRAWING NUMBER</text>'
        f'<text x="{{mid_x+20}}" y="{{title_y+27}}" font-size="14" font-weight="bold" dominant-baseline="middle">{{meta["part_no"]}}</text>'
    )

    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?>\\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{{W:.2f}}mm" height="{{H+60:.2f}}mm" '
        f'viewBox="0 0 {{W:.2f}} {{H+60:.2f}}">\\n'
        + "\\n".join(paths) + "\\n"
        + dim_svg + "\\n"
        + title_svg + "\\n"
        + '</svg>\\n'
    )

    with open(r"{opath}", "w", encoding="utf-8") as f:
        f.write(svg)

    print("drawing export OK", flush=True)
    App.closeDocument(doc.Name)
    print("TECHDRAW_DONE", flush=True)
'''