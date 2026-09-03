"""
Run from project root:
    python head_extrude_test.py [width_mm] [H_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Geometry, per notebook sketch:
  - Profile lies in the YZ plane at X=0 (points -> V(0.0, x, z)),
    same convention as threshold_geometry.py.
  - Extrude along +X for `width_mm` (window/door width).
  - Translate the solid by +(H - head_y_extent) on Y, so the head's OWN
    Y-extent (90mm, from its bbox) nests flush inside the jamb's Y=0..H
    range at the top — mirroring how threshold nests flush at Y=0..165
    at the bottom. Previous version translated by +H only, which pushed
    the head entirely above Y=H (floating above the frame, gap visible
    in FreeCAD render).

Output: output/head_test.step
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.head_geometry import HEAD_PROFILE_POINTS, get_head_bbox, draw_head_section

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_step(width_mm: float, H_mm: float, step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    minx, miny, maxx, maxy = get_head_bbox()
    head_y_extent = maxx - minx  # local-x extent -> global Y extent

    params_path = os.path.join(tempfile.gettempdir(), "head_test_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "points": HEAD_PROFILE_POINTS,
            "width_mm": width_mm,
            "H_mm": H_mm,
            "head_y_extent": head_y_extent,
            "step_path": step_path,
        }, f)

    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

try:
    data = json.load(open(r"{params_path}", encoding="utf-8"))
    pts_2d = data["points"]
    L = float(data["width_mm"])
    H = float(data["H_mm"])
    head_y_extent = float(data["head_y_extent"])
    step_path = data["step_path"]

    # Plane YZ at X=0 — profile must be perpendicular to the extrude
    # direction (X) or the extrude is degenerate (zero volume). Same
    # convention as threshold: profile's (x, y) -> world (0, Y, Z).
    pts = [V(0.0, float(x), float(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate face, area={{face.Area}}")

    # Extrude in X direction for the window/door width.
    solid = face.extrude(V(L, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty extrude, volume={{solid.Volume}}")

    # Nest head's own Y-extent (90mm) into the top of the frame's Y=0..H
    # span, instead of floating above Y=H.
    solid.translate(V(0.0, H - head_y_extent, 0.0))

    doc = App.newDocument("HeadTest")
    obj = doc.addObject("Part::Feature", "Head")
    obj.Shape = solid
    doc.recompute()

    solid.exportStep(step_path)
    bb = solid.BoundBox
    print(f"OK bbox=({{bb.XLength:.2f}},{{bb.YLength:.2f}},{{bb.ZLength:.2f}}) "
          f"YMin={{bb.YMin:.2f}} YMax={{bb.YMax:.2f}} volume={{solid.Volume:.1f}}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
'''
    script_path = os.path.join(tempfile.gettempdir(), "head_test_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    env = os.environ.copy()
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    result = subprocess.run([freecad, script_path], capture_output=True, text=True,
                             timeout=120, env=env)
    print("--- FreeCAD stdout ---")
    print(result.stdout)
    if result.stderr.strip():
        print("--- FreeCAD stderr ---")
        print(result.stderr)
    if "SCRIPT_ERROR" in result.stdout or result.returncode != 0:
        return False
    return os.path.isfile(step_path)


def export_dxf(dxf_path: str, H_mm: float):
    import ezdxf
    from app.services.dxf_layers import setup_layers, setup_dimstyle

    minx, miny, maxx, maxy = get_head_bbox()
    head_y_extent = maxx - minx

    doc = ezdxf.new("R2010", setup=True)
    setup_layers(doc)
    setup_dimstyle(doc, bar_width=40.0)
    msp = doc.modelspace()

    # Drawn at Y-offset (H - head_y_extent) to match the 3D nested position.
    draw_head_section(msp, origin=(0.0, H_mm - head_y_extent), layer="WINDOW_CILL")
    doc.saveas(dxf_path)
    return os.path.isfile(dxf_path)


def main():
    width_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    H_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1200.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    minx, miny, maxx, maxy = get_head_bbox()
    print(f"Profile bbox: {maxx - minx:.2f} x {maxy - miny:.2f} mm")
    print(f"Extrude width (X): {width_mm} mm, top offset (Y): {H_mm} mm")

    step_path = os.path.join(OUTPUT_DIR, "head_test.step")
    dxf_path = os.path.join(OUTPUT_DIR, "head_section.dxf")

    step_ok = export_step(width_mm, H_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")

    dxf_ok = export_dxf(dxf_path, H_mm)
    print(f"DXF export:  {'OK -> ' + dxf_path if dxf_ok else 'FAILED'}")


if __name__ == "__main__":
    main()