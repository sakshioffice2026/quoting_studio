"""
app/services/techdraw_export.py — 2D drawing export via FreeCAD TechDraw.

Pipeline (replaces ezdxf DXF generation):
  1. Build the window assembly and export it to a STEP file
     (reuses model3d_freecad.generate_3d_freecad(fmt='step')).
  2. Launch freecadcmd: import the STEP file with Import.insert(),
     create a TechDraw page with:
       - front DrawViewPart (elevation)
       - DrawViewSection (horizontal cut through the frame, hatched)
       - overall width/height DrawViewDimension objects
       - title block fields populated (part no., material, scale, date)
     and export the page to SVG or PDF.
"""
from __future__ import annotations
import os, json, subprocess, tempfile, logging
from datetime import date

from .model3d_freecad import _find_freecad, _read

logger = logging.getLogger(__name__)


def _find_freecad_gui(freecadcmd_path: str) -> str | None:
    """
    TechDraw SVG/PDF export needs real Qt rendering (QSvgGenerator etc.),
    which freecadcmd.exe's Gui stub (FreeCADGui.setupWithoutGUI()) cannot
    provide — it crashes with an access violation when the export actually
    tries to paint. The full GUI binary (FreeCAD.exe), run headless via
    QT_QPA_PLATFORM=offscreen, is required instead. It normally sits next
    to freecadcmd.exe in the same bin/ folder.
    """
    import glob
    bin_dir = os.path.dirname(freecadcmd_path)
    for name in ('FreeCAD.exe', 'freecad.exe', 'FreeCADGui.exe',
                 'FreeCAD', 'freecad'):
        candidate = os.path.join(bin_dir, name)
        if os.path.exists(candidate) and candidate.lower() != freecadcmd_path.lower():
            return candidate
    for pat in ('FreeCAD*.exe',):
        for hit in glob.glob(os.path.join(bin_dir, pat)):
            if 'cmd' not in os.path.basename(hit).lower():
                return hit
    return None


def generate_techdraw(window, panes, tenant_id=None, fmt='svg') -> bytes:
    """
    Generate a 2D engineering drawing (SVG or PDF) from the window's STEP
    model using FreeCAD's TechDraw module. Raises RuntimeError on failure.
    """
    fmt = fmt.lower()
    if fmt not in ('svg', 'pdf'):
        raise ValueError("fmt must be 'svg' or 'pdf'")

    freecad = _find_freecad()
    if not freecad:
        raise RuntimeError('FreeCAD not found — tried all known paths')

    freecad_gui = _find_freecad_gui(freecad)
    if not freecad_gui:
        raise RuntimeError(
            'FreeCAD GUI binary (FreeCAD.exe) not found next to freecadcmd — '
            'required for TechDraw SVG/PDF export. freecadcmd.exe alone '
            'cannot render TechDraw pages.')

    from .model3d_freecad import generate_3d_freecad
    step_bytes = generate_3d_freecad(window, panes, tenant_id=tenant_id, fmt='step')
    if not step_bytes:
        raise RuntimeError('STEP generation failed — cannot build TechDraw page')

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
    out_path    = os.path.join(tmp_dir, f'qs_td_out_{wid}.{fmt}')

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
            f.write(_build_script(step_path, meta_path, out_path, fmt))

        env = os.environ.copy()
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        env['QT_QPA_PLATFORM'] = 'offscreen'
        # Use the full GUI binary (not freecadcmd) with --console so TechDraw's
        # Qt-based SVG/PDF export has a real (offscreen) Qt application to
        # paint into, instead of the freecadcmd Gui stub that crashes on export.
        r = subprocess.run([freecad_gui, '--console', script_path],
                           capture_output=True, text=True,
                           timeout=180, env=env)
        logger.debug('FreeCAD TechDraw stdout: %s', (r.stdout or '')[-2000:])
        if r.stderr:
            logger.warning('FreeCAD TechDraw stderr: %s', r.stderr[-1000:])

        if 'TECHDRAW_DONE' not in (r.stdout or ''):
            raise RuntimeError(
                f'FreeCAD TechDraw script did not complete. '
                f'stdout: {(r.stdout or "")[-1000:]} '
                f'stderr: {(r.stderr or "")[-1000:]}')

        return _read(out_path)

    finally:
        for p in (step_path, meta_path, script_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def _build_script(step_path: str, meta_path: str, out_path: str, fmt: str) -> str:
    spath = step_path.replace('\\', '/')
    mpath = meta_path.replace('\\', '/')
    opath = out_path.replace('\\', '/')

    return f'''
import FreeCAD as App
import FreeCADGui
# Running under the real FreeCAD.exe --console binary (not freecadcmd), so
# FreeCADGui is already initialised with a genuine (offscreen) Qt app.
# Do NOT call FreeCADGui.setupWithoutGUI() here — that stub is for
# freecadcmd.exe and crashes (access violation) when TechDrawGui tries to
# actually paint an SVG/PDF export.
import Import, TechDraw, TechDrawGui, glob, os, json

meta = json.load(open(r"{mpath}", encoding="utf-8"))

doc = App.newDocument("QS_TechDraw")

# 1. Import the STEP file
Import.insert(r"{spath}", doc.Name)
doc.recompute()
shapes = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
if not shapes:
    print("ERROR: no shapes imported from STEP", flush=True)
else:
    # 2. TechDraw page + template
    template_path = None
    for base in (App.getResourceDir(),):
        for pat in ("Mod/TechDraw/Templates/A4_Landscape_blank.svg",
                    "Mod/TechDraw/Templates/A4_Landscape.svg",
                    "Mod/TechDraw/Templates/*.svg"):
            hits = glob.glob(os.path.join(base, pat))
            if hits:
                template_path = hits[0]
                break
        if template_path:
            break

    page = doc.addObject("TechDraw::DrawPage", "Page")
    template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    if template_path:
        template.Template = template_path
    page.Template = template

    # 3a. Front view (elevation) — primary orthographic projection
    front = doc.addObject("TechDraw::DrawViewPart", "Elevation")
    front.Source = shapes
    front.Direction = App.Vector(0, 0, 1)
    front.Scale = 1.0
    front.X = 120
    front.Y = 150
    page.addView(front)
    doc.recompute()

    # 3b. Horizontal section view — cut through the frame depth, hatched.
    # Cutting plane normal is horizontal (X axis) so the section shows the
    # jamb/mullion profile in cross-section, per fabrication drawing convention.
    section = doc.addObject("TechDraw::DrawViewSection", "SectionAA")
    section.BaseView = front
    section.Source = shapes
    section.SectionNormal = App.Vector(1, 0, 0)
    section.SectionOrigin = front.Source[0].Shape.BoundBox.Center if front.Source else App.Vector(0, 0, 0)
    section.Direction = App.Vector(1, 0, 0)
    section.Scale = front.Scale
    section.X = front.X + 260
    section.Y = front.Y
    try:
        page.addView(section)
        doc.recompute()
        section_ok = True
    except Exception as e:
        print("section view failed:", e, flush=True)
        try:
            doc.removeObject(section.Name)
        except Exception:
            pass
        section_ok = False

    # 4. Overall width / height dimensions on the elevation view.
    def _add_dim(name, dim_type, edge_ref):
        try:
            dim = doc.addObject("TechDraw::DrawViewDimension", name)
            dim.Type = dim_type
            dim.References2D = [(front, edge_ref)]
            dim.FormatSpec = "%dim%"
            page.addView(dim)
            doc.recompute()
            return True
        except Exception as e:
            print(f"dimension {{name}} failed:", e, flush=True)
            try:
                doc.removeObject(dim.Name)
            except Exception:
                pass
            return False

    dims_ok = _add_dim("DimWidth", "DistanceX", "Edge1")
    dims_ok = _add_dim("DimHeight", "DistanceY", "Edge2") or dims_ok

    if not dims_ok:
        # Fallback: plain text annotation with overall size so the sheet is
        # never delivered without a stated width/height.
        try:
            note = doc.addObject("TechDraw::DrawViewAnnotation", "SizeNote")
            note.Text = [f"OVERALL SIZE: {{meta['width']:.0f}} x {{meta['height']:.0f}} mm"]
            note.X = front.X
            note.Y = front.Y - 140
            page.addView(note)
            doc.recompute()
        except Exception as e:
            print("size annotation failed:", e, flush=True)

    # 5. Title block — populate common template edit fields (best-effort;
    # unknown/missing fields on a given template are silently skipped).
    fields = {{
        "PARTNO":     meta["part_no"],
        "PART_NO":    meta["part_no"],
        "TITLE":      meta["label"],
        "MATERIAL":   meta["material"],
        "SCALE":      meta["scale"],
        "DATE":       meta["date"],
        "DRAWN_BY":   "QUOTING STUDIO",
        "SheetNumber":"1",
    }}
    for key, val in fields.items():
        try:
            template.setEditFieldContent(key, str(val))
        except Exception:
            pass
    doc.recompute()

    # 6. Export to SVG or PDF
    if "{fmt}" == "svg":
        TechDrawGui.exportPageAsSvg(page, r"{opath}")
    else:
        TechDrawGui.exportPageAsPdf(page, r"{opath}")

    try:
        _sz = os.path.getsize(r"{opath}")
        print(f"TechDraw export OK ({{_sz}} bytes)", flush=True)
    except Exception as _e:
        print("export size check failed:", _e, flush=True)

App.closeDocument(doc.Name)
print("TECHDRAW_DONE", flush=True)
'''