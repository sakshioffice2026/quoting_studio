"""
Run from project root:
    python frame_assembly_test.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

ITEM 1 — RELATIVE POSITIONING / SNAP CONSTRAINTS
--------------------------------------------------
Members are still extruded and rotated exactly as before (that
local-to-final coordinate mapping was already verified against real
STEP output). What changed is placement: instead of hand-computed
.translate(V(...)) offsets, each member is now SNAPPED onto the
shared frame boundary using its own real BoundBox in the final
(width=X, depth=Y, height=Z) frame:

    jamb_left  -> X min = 0,        Z min = 0
    jamb_right -> X max = width_mm, Z min = 0
    threshold  -> X min = 0,        Z min = 0
    head       -> X min = 0,        Z max = height_mm
    all four   -> Y min = 0 (shared depth/back-face reference)

Because the snap is computed from actual solid geometry (not
assumed profile min/max), members always meet flush at their shared
edges regardless of source-DXF quirks. Miter cuts are NOT part of
this step (next item).

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
from app.services.head_geometry import (
    get_profile_points_normalised as head_pts,
)
from app.services.jamb_geometry import (
    get_profile_points_normalised as jamb_pts,
)

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

    params_path = os.path.join(tempfile.gettempdir(), "frame_assembly_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold_pts": threshold_pts(),
            "head_pts": head_pts(),
            "jamb_pts": jamb_pts(),
            "width_mm": width_mm,
            "height_mm": height_mm,
            "step_path": step_path,
        }, f)

    script = r"""
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

def _extrude_horizontal(pts_2d, length):
    # Local frame pre-rotation: profile lies in the Y-Z plane (X=0),
    # extruded along X by 'length'. X is unaffected by the later
    # +90deg-about-X rotation, so this axis already matches final
    # frame width directly.
    min_y_axis = min(float(x) for x, _ in pts_2d)
    pts = [V(0.0, float(x) - min_y_axis, -float(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("horizontal profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate horizontal face, area={face.Area}")
    solid = face.extrude(V(length, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty horizontal extrude, volume={solid.Volume}")
    return solid

def _extrude_vertical(pts_2d, length):
    # Local frame pre-rotation, matching jamb_extrude_test.py's
    # confirmed-working (u, v) -> V(u, 0, v) mapping.
    v_extent = max(float(v) for _, v in pts_2d)
    pts = [V(float(u), 0.0, float(v) - v_extent) for u, v in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("vertical profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid/degenerate vertical face, area={face.Area}")
    solid = face.extrude(V(0.0, length, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid/empty vertical extrude, volume={solid.Volume}")
    return solid

def _rotate_x90(solid):
    # Rigid-body +90deg about world X: X->X, Y->Z, Z->-Y.
    # Establishes final frame: X=width, Y=depth, Z=height.
    solid.rotate(V(0.0, 0.0, 0.0), V(1.0, 0.0, 0.0), 90.0)

def _snap(solid, x=None, y=None, z=None):
    # Translate solid so its BoundBox satisfies the given target(s).
    # Each target is (edge, value), edge in ('min', 'max').
    bb = solid.BoundBox
    dx = dy = dz = 0.0
    if x is not None:
        edge, val = x
        cur = bb.XMin if edge == "min" else bb.XMax
        dx = val - cur
    if y is not None:
        edge, val = y
        cur = bb.YMin if edge == "min" else bb.YMax
        dy = val - cur
    if z is not None:
        edge, val = z
        cur = bb.ZMin if edge == "min" else bb.ZMax
        dz = val - cur
    solid.translate(V(dx, dy, dz))

try:
    data = json.load(open(r"__PARAMS_PATH__", encoding="utf-8"))
    threshold_pts_2d = data["threshold_pts"]
    head_pts_2d      = data["head_pts"]
    jamb_pts_2d      = data["jamb_pts"]
    W                = float(data["width_mm"])
    H                = float(data["height_mm"])
    step_path        = data["step_path"]

    threshold  = _extrude_horizontal(threshold_pts_2d, W)
    head       = _extrude_horizontal(head_pts_2d, W)
    jamb_left  = _extrude_vertical(jamb_pts_2d, H)
    jamb_right = _extrude_vertical(jamb_pts_2d, H)

    for solid in (threshold, head, jamb_left, jamb_right):
        _rotate_x90(solid)

    # ---- SNAP CONSTRAINTS (relative positioning) -------------------
    # Shared depth reference plane for all four members.
    DEPTH_REF = ("min", 0.0)

    _snap(jamb_left,  x=("min", 0.0), y=DEPTH_REF, z=("min", 0.0))
    _snap(jamb_right, x=("max", W),   y=DEPTH_REF, z=("min", 0.0))
    _snap(threshold,  x=("min", 0.0), y=DEPTH_REF, z=("min", 0.0))
    _snap(head,       x=("min", 0.0), y=DEPTH_REF, z=("max", H))

    doc = App.newDocument("FrameAssemblyTest")
    o1 = doc.addObject("Part::Feature", "Threshold"); o1.Shape = threshold
    o2 = doc.addObject("Part::Feature", "Head");      o2.Shape = head
    o3 = doc.addObject("Part::Feature", "JambLeft");  o3.Shape = jamb_left
    o4 = doc.addObject("Part::Feature", "JambRight"); o4.Shape = jamb_right
    doc.recompute()

    compound = Part.makeCompound([threshold, head, jamb_left, jamb_right])
    compound.exportStep(step_path)

    bb = compound.BoundBox
    print(f"OK compound bbox=({bb.XLength:.2f},{bb.YLength:.2f},{bb.ZLength:.2f}) "
          f"XMin={bb.XMin:.2f} XMax={bb.XMax:.2f} "
          f"YMin={bb.YMin:.2f} YMax={bb.YMax:.2f} "
          f"ZMin={bb.ZMin:.2f} ZMax={bb.ZMax:.2f}")
    print(f"threshold volume={threshold.Volume:.1f} "
          f"head volume={head.Volume:.1f} "
          f"jamb_left volume={jamb_left.Volume:.1f} "
          f"jamb_right volume={jamb_right.Volume:.1f}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
"""
    script = script.replace("__PARAMS_PATH__", params_path.replace("\\", "/"))

    script_path = os.path.join(tempfile.gettempdir(), "frame_assembly_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    env = os.environ.copy()
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    result = subprocess.run(
        [freecad, script_path],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
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

    print(f"Assembly: width(X)={width_mm} mm, height(Z)={height_mm} mm")

    step_path = os.path.join(OUTPUT_DIR, "frame_assembly_test.step")
    step_ok = export_assembly_step(width_mm, height_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")


if __name__ == "__main__":
    main()