"""
Run from project root:
    python frame_assembly_test.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Conventions:
  - threshold: (x,y) -> V(0,x,y), extrude +X by width_mm.
               Front face flush at Z=0. No Y-translate (nests at bottom).
  - head:      (x,y) -> V(0,x,y), extrude +X by width_mm.
               Front face flush at Z=0. Translate +(H - head_y_extent)
               on Y (nests at top).
  - jamb:      (u,v) -> V(u,0,v), extrude +Y by height_mm. UNCHANGED.
               Front face flush at Z=0 (v starts at 0, same as
               threshold/head) — this is what aligns jamb's outer
               surface with threshold's and head's outer surface.
               Left jamb: no translate (X=0).
               Right jamb: translate +X by width_mm.

Output: output/frame_assembly_test.step
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.threshold_geometry import (
    get_profile_points_normalised as threshold_pts,
)
from app.services.head_geometry import HEAD_PROFILE_POINTS, get_head_bbox
from app.services.jamb_geometry import JAMB_PROFILE_POINTS

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_assembly_step(width_mm: float, height_mm: float, step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    minx, miny, maxx, maxy = get_head_bbox()
    head_y_extent = maxx - minx

    params_path = os.path.join(tempfile.gettempdir(), "frame_assembly_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold_pts": threshold_pts(),
            "head_pts": HEAD_PROFILE_POINTS,
            "jamb_pts": JAMB_PROFILE_POINTS,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "head_y_extent": head_y_extent,
            "step_path": step_path,
        }, f)

    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

def _extrude_horizontal(pts_2d, length):
    # Front face flush at Z=0 (points as-given, normalised >=0).
    pts = [V(0.0, float(x), float(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("horizontal profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate horizontal face, area={{face.Area}}")
    solid = face.extrude(V(length, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty horizontal extrude, volume={{solid.Volume}}")
    return solid

def _extrude_vertical(pts_2d, length):
    # Front face flush at Z=0 (points as-given, normalised >=0) —
    # same front-face reference as threshold/head, so jamb's outer
    # surface lines up with theirs.
    pts = [V(float(u), 0.0, float(v)) for u, v in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("vertical profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate vertical face, area={{face.Area}}")
    solid = face.extrude(V(0.0, length, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty vertical extrude, volume={{solid.Volume}}")
    return solid

try:
    data = json.load(open(r"{params_path}", encoding="utf-8"))
    threshold_pts   = data["threshold_pts"]
    head_pts        = data["head_pts"]
    jamb_pts        = data["jamb_pts"]
    W               = float(data["width_mm"])
    H               = float(data["height_mm"])
    head_y_extent   = float(data["head_y_extent"])
    step_path       = data["step_path"]

    threshold = _extrude_horizontal(threshold_pts, W)

    head = _extrude_horizontal(head_pts, W)
    head.translate(V(0.0, H - head_y_extent, 0.0))

    jamb_left = _extrude_vertical(jamb_pts, H)

    jamb_right = jamb_left.copy()
    jamb_right.translate(V(W, 0.0, 0.0))

    doc = App.newDocument("FrameAssemblyTest")
    o1 = doc.addObject("Part::Feature", "Threshold"); o1.Shape = threshold
    o2 = doc.addObject("Part::Feature", "Head");      o2.Shape = head
    o3 = doc.addObject("Part::Feature", "JambLeft");  o3.Shape = jamb_left
    o4 = doc.addObject("Part::Feature", "JambRight"); o4.Shape = jamb_right
    doc.recompute()

    compound = Part.makeCompound([threshold, head, jamb_left, jamb_right])
    compound.exportStep(step_path)

    bb = compound.BoundBox
    print(f"OK compound bbox=({{bb.XLength:.2f}},{{bb.YLength:.2f}},{{bb.ZLength:.2f}}) "
          f"XMin={{bb.XMin:.2f}} XMax={{bb.XMax:.2f}} "
          f"YMin={{bb.YMin:.2f}} YMax={{bb.YMax:.2f}} "
          f"ZMin={{bb.ZMin:.2f}} ZMax={{bb.ZMax:.2f}}")
    print(f"threshold volume={{threshold.Volume:.1f}} "
          f"head volume={{head.Volume:.1f}} "
          f"jamb_left volume={{jamb_left.Volume:.1f}} "
          f"jamb_right volume={{jamb_right.Volume:.1f}}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
'''
    script_path = os.path.join(tempfile.gettempdir(), "frame_assembly_script.py")
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


def main():
    width_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    height_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1200.0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Assembly: width(X)={width_mm} mm, height(Y)={height_mm} mm")

    step_path = os.path.join(OUTPUT_DIR, "frame_assembly_test.step")
    step_ok = export_assembly_step(width_mm, height_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")


if __name__ == "__main__":
    main()