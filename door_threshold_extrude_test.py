"""
Run from project root:
    python door_threshold_extrude_test.py [length_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py. Two independent outputs, both from the same
hardcoded profile (app/services/threshold_geometry.py):

  1. <output>/threshold_test.step  — 3D solid, profile extruded along
     +X for `length_mm` (default 1000mm), via FreeCAD (subprocess,
     same _find_freecad() discovery as app/services/model3d_freecad.py).
  2. <output>/threshold_section.dxf — 2D engineering cross-section
     drawing (profile + overall width/height dims) using this repo's
     existing dxf_layers.py layer/dimstyle setup and the same
     add_aligned_dim(...).render() pattern as engineering_dxf.py.

Sanity-checks the STEP result's bounding box against the known profile
bbox (165 x 60 mm) x length_mm before declaring success.
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.threshold_geometry import (
    get_profile_points_normalised, get_bbox, draw_threshold_section,
)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_step(length_mm: float, step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    pts = get_profile_points_normalised()
    params_path = os.path.join(tempfile.gettempdir(), "threshold_test_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({"points": pts, "length_mm": length_mm, "step_path": step_path}, f)

    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

try:
    data = json.load(open(r"{params_path}", encoding="utf-8"))
    pts_2d = data["points"]
    L = float(data["length_mm"])
    step_path = data["step_path"]

    # Profile lies in the YZ plane at X=0; extrude along +X — same
    # convention as make_face_rings()/face.extrude(V(L,0,0)) in
    # app/services/model3d_freecad.py for horizontal members.
    pts = [V(0.0, float(x), float(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate face, area={{face.Area}}")

    solid = face.extrude(V(L, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty extrude, volume={{solid.Volume}}")

    doc = App.newDocument("ThresholdTest")
    obj = doc.addObject("Part::Feature", "DoorThreshold")
    obj.Shape = solid
    doc.recompute()

    solid.exportStep(step_path)
    bb = solid.BoundBox
    print(f"OK bbox=({{bb.XLength:.2f}},{{bb.YLength:.2f}},{{bb.ZLength:.2f}}) "
          f"volume={{solid.Volume:.1f}}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
'''
    script_path = os.path.join(tempfile.gettempdir(), "threshold_test_script.py")
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


def export_dxf(dxf_path: str):
    import ezdxf
    from app.services.dxf_layers import setup_layers, setup_dimstyle

    doc = ezdxf.new("R2010", setup=True)
    setup_layers(doc)
    setup_dimstyle(doc, bar_width=40.0)
    msp = doc.modelspace()

    draw_threshold_section(msp, origin=(0.0, 0.0), layer="WINDOW_CILL")
    doc.saveas(dxf_path)
    return os.path.isfile(dxf_path)


def main():
    length_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    minx, miny, maxx, maxy = get_bbox()
    print(f"Profile bbox: {maxx - minx:.2f} x {maxy - miny:.2f} mm "
          f"(expected 165.00 x 60.00)")

    step_path = os.path.join(OUTPUT_DIR, "threshold_test.step")
    dxf_path = os.path.join(OUTPUT_DIR, "threshold_section.dxf")

    step_ok = export_step(length_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")

    dxf_ok = export_dxf(dxf_path)
    print(f"DXF export:  {'OK -> ' + dxf_path if dxf_ok else 'FAILED'}")


if __name__ == "__main__":
    main()