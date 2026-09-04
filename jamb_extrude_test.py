"""
Run from project root:
    python jamb_extrude_test.py [height_mm] [width_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Geometry (plane='XY' convention — ITEM 1 fix):
  - Profile in XY plane at Z=0: (u, v) -> V(u, v, 0.0)
  - Extrude along +Z for height_mm (vertical member length).
  - Left jamb: no translation (X=0 left edge).
  - Right jamb: translate solid by V(width_mm, 0, 0).

Output:
    output/jamb_left_test.step   — left jamb solid
    output/jamb_right_test.step  — right jamb solid (translated)
    output/jamb_section.dxf      — 2D cross-section (natural orientation)
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib.util

def _load(rel):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
    spec = importlib.util.spec_from_file_location('_mod', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

jamb_mod = _load('app/services/jamb_geometry.py')
JAMB_PROFILE_POINTS = jamb_mod.get_profile_points_normalised()
get_jamb_bbox       = jamb_mod.get_jamb_bbox
draw_jamb_section   = jamb_mod.draw_jamb_section

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    fc_mod = _load('app/services/model3d_freecad.py')
    return fc_mod._find_freecad()


def export_step(height_mm: float, width_mm: float,
                step_left: str, step_right: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False, False

    params_path = os.path.join(tempfile.gettempdir(), "jamb_test_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "points":     JAMB_PROFILE_POINTS,
            "height_mm":  height_mm,
            "width_mm":   width_mm,
            "step_left":  step_left,
            "step_right": step_right,
        }, f)

    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

try:
    data      = json.load(open(r"{params_path}", encoding="utf-8"))
    pts_2d    = data["points"]
    H         = float(data["height_mm"])
    W         = float(data["width_mm"])
    step_left  = data["step_left"]
    step_right = data["step_right"]

    # plane='XY': profile sketched in XY plane at Z=0 — (u,v) -> V(u, v, 0)
    # Extrude along +Z for height_mm (vertical member).
    pts = [V(float(u), float(v), 0.0) for u, v in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate face, area={{face.Area}}")

    # Left jamb at X=0
    left = face.extrude(V(0.0, 0.0, H))
    if not left.isValid() or left.Volume <= 1.0:
        raise RuntimeError(f"invalid left extrude, volume={{left.Volume}}")

    # Right jamb: translate left solid by V(width_mm, 0, 0)
    right = left.copy()
    right.translate(V(W, 0.0, 0.0))

    doc = App.newDocument("JambTest")
    ol = doc.addObject("Part::Feature", "JambLeft");  ol.Shape = left
    or_ = doc.addObject("Part::Feature", "JambRight"); or_.Shape = right
    doc.recompute()

    left.exportStep(step_left)
    right.exportStep(step_right)

    bb = left.BoundBox
    print(f"OK left  bbox=({{bb.XLength:.2f}},{{bb.YLength:.2f}},{{bb.ZLength:.2f}}) "
          f"volume={{left.Volume:.1f}}")
    bb2 = right.BoundBox
    print(f"OK right bbox=({{bb2.XLength:.2f}},{{bb2.YLength:.2f}},{{bb2.ZLength:.2f}}) "
          f"XMin={{bb2.XMin:.2f}}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
'''
    script_path = os.path.join(tempfile.gettempdir(), "jamb_test_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    env = os.environ.copy()
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    result = subprocess.run([freecad, script_path], capture_output=True,
                             text=True, timeout=120, env=env)
    print("--- FreeCAD stdout ---")
    print(result.stdout)
    if result.stderr.strip():
        print("--- FreeCAD stderr ---")
        print(result.stderr)
    if "SCRIPT_ERROR" in result.stdout or result.returncode != 0:
        return False, False
    return os.path.isfile(step_left), os.path.isfile(step_right)


def export_dxf(dxf_path: str):
    import ezdxf
    dl = _load('app/services/dxf_layers.py')
    doc = ezdxf.new("R2010", setup=True)
    dl.setup_layers(doc)
    dl.setup_dimstyle(doc, bar_width=40.0)
    msp = doc.modelspace()
    draw_jamb_section(msp, origin=(0.0, 0.0), layer="FRAME_GEOMETRY")
    doc.saveas(dxf_path)
    return os.path.isfile(dxf_path)


def main():
    height_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1200.0
    width_mm  = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    minx, miny, maxx, maxy = get_jamb_bbox()
    print(f"Profile bbox: {maxx - minx:.2f} x {maxy - miny:.2f} mm "
          f"(expected 67.00 x 90.00)")
    print(f"Extrude height (Y): {height_mm} mm, frame width (X): {width_mm} mm")

    step_left  = os.path.join(OUTPUT_DIR, "jamb_left_test.step")
    step_right = os.path.join(OUTPUT_DIR, "jamb_right_test.step")
    dxf_path   = os.path.join(OUTPUT_DIR, "jamb_section.dxf")

    left_ok, right_ok = export_step(height_mm, width_mm, step_left, step_right)
    print(f"STEP left:  {'OK -> ' + step_left  if left_ok  else 'FAILED'}")
    print(f"STEP right: {'OK -> ' + step_right if right_ok else 'FAILED'}")

    dxf_ok = export_dxf(dxf_path)
    print(f"DXF export: {'OK -> ' + dxf_path if dxf_ok else 'FAILED'}")


if __name__ == "__main__":
    main()