"""
Run from project root:
    python threshold_jamb_assembly_test.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Builds threshold + left_jamb + right_jamb + head in ONE shared
coordinate space (world X=width, Y=exterior<->interior depth,
Z=floor-up height). Both jambs snap their bottom face onto the
threshold's Z-max, flush at X=0.0 (left) / X=W (right), rear edge
flush with the threshold's rear upstand, then boolean-cut against
the threshold to notch out any overlap. The head spans the full
width and rests on top of both jambs. All four grouped into a
single FreeCAD Part.makeCompound() (OpenCASCADE TopoDS_Compound)
and exported as ONE combined STEP file.

NOT included yet (separate item): inward-facing jamb rotation.

Output: output/threshold_jamb_assembly.step
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
from app.services.jamb_geometry import (
    get_profile_points_normalised as jamb_pts,
)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_combined_step(width_mm: float, height_mm: float, step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    params_path = os.path.join(tempfile.gettempdir(), "threshold_jamb_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold_pts": threshold_pts(),
            "jamb_pts": jamb_pts(),
            "width_mm": width_mm,
            "height_mm": height_mm,
            "step_path": step_path,
        }, f)

    script = r"""
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

def _build_threshold(pts_2d, W):
    # Same pitch + drainage-orientation logic as
    # door_threshold_extrude_test.py: world-Y = local-x (ext<->int
    # footprint), world-Z = local-y (floor-up height).
    x_vals = [float(x) for x, _ in pts_2d]
    y_vals = [float(y) for _, y in pts_2d]
    x_mid = (min(x_vals) + max(x_vals)) / 2.0
    ramp_xs = [x for x in x_vals if x <= x_mid]
    dam_xs  = [x for x in x_vals if x > x_mid]
    ramp_avg = sum(ramp_xs) / len(ramp_xs) if ramp_xs else 0.0
    dam_avg  = sum(dam_xs) / len(dam_xs) if dam_xs else 0.0

    EXTERIOR_AT_Y_MIN = True
    x_extent = max(x_vals) - min(x_vals)
    currently_ramp_at_min = ramp_avg <= dam_avg
    needs_mirror = currently_ramp_at_min != EXTERIOR_AT_Y_MIN

    def _oriented_y(x):
        x0 = float(x) - min(x_vals)
        return (x_extent - x0) if needs_mirror else x0

    def _floor_up_z(y):
        return float(y) - min(y_vals)

    pts = [V(0.0, _oriented_y(x), _floor_up_z(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("threshold wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid threshold face, area={face.Area}")
    solid = face.extrude(V(W, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid threshold extrude, volume={solid.Volume}")
    return solid

def _build_jamb(pts_2d, H):
    # plane='XY' (ITEM 1 fix): (u, v) -> V(u, v, 0), extrude +Z by H.
    pts = [V(float(u), float(v), 0.0) for u, v in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("jamb wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid jamb face, area={face.Area}")
    solid = face.extrude(V(0.0, 0.0, H))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid jamb extrude, volume={solid.Volume}")
    return solid

def _build_head(jamb_pts_2d, W):
    # Uses the SAME jamb profile (67x90mm) instead of the old
    # rectangular head profile. Cross-section built in the Y-Z plane,
    # extruded along +X by W.
    #   world-Y = local-v (depth through wall) — matches the jamb's
    #     own direct v->Y mapping, so the header shares the exact
    #     same depth reference as the jambs for a flush joint.
    #   world-Z = mirrored local-u — the header is the jamb profile
    #     rotated so its channel/stop faces DOWN (-Z) into the
    #     opening. Flip MIRROR_CHANNEL_Z if it points the wrong way.
    MIRROR_CHANNEL_Z = True
    u_vals = [float(u) for u, _ in jamb_pts_2d]
    u_extent = max(u_vals) - min(u_vals)

    def _z(u):
        u0 = float(u) - min(u_vals)
        return (u_extent - u0) if MIRROR_CHANNEL_Z else u0

    pts = [V(0.0, float(v), _z(u)) for u, v in jamb_pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("head wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError(f"invalid head face, area={face.Area}")
    solid = face.extrude(V(W, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError(f"invalid head extrude, volume={solid.Volume}")
    return solid

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
    jamb_pts_2d      = data["jamb_pts"]
    W                = float(data["width_mm"])
    H                = float(data["height_mm"])
    step_path        = data["step_path"]

    threshold = _build_threshold(threshold_pts_2d, W)
    _snap(threshold, x=("min", 0.0), y=("min", 0.0), z=("min", 0.0))
    threshold_zmax = threshold.BoundBox.ZMax
    threshold_ymax = threshold.BoundBox.YMax

    def _place_jamb(x_target):
        jamb = _build_jamb(jamb_pts_2d, H)
        # Bottom face (Zmin) snaps to the threshold's highest point
        # (Zmax of the interior upstand), flush at the given X edge.
        _snap(jamb, x=x_target, z=("min", threshold_zmax))
        # Depth (Y): align the jamb's REAR edge (Ymax) flush with the
        # threshold's rear upstand edge (Ymax) instead of a front
        # (Ymin) reference.
        _snap(jamb, y=("max", threshold_ymax))
        # Boolean notch: cut threshold's volume out of the jamb
        # wherever they intersect (e.g. a jamb edge overhanging the
        # threshold's sloped ramp section). Always attempted — a
        # strict BoundBox overlap check can miss coincident/touching
        # geometry right at the joint.
        cut_result = jamb.cut(threshold)
        if cut_result.isValid() and cut_result.Volume > 1.0:
            return cut_result
        print("NOTE: jamb.cut(threshold) produced no valid change "
              "(no intersecting volume) — keeping uncut jamb.")
        return jamb

    left_jamb  = _place_jamb(("min", 0.0))
    right_jamb = _place_jamb(("max", W))
    jambs_top  = max(left_jamb.BoundBox.ZMax, right_jamb.BoundBox.ZMax)

    head = _build_head(jamb_pts_2d, W)
    # Spans the full width (X=0..W) so it sits across both jambs;
    # bottom face (Zmin) rests on the jambs' top; rear edge (Ymax)
    # kept flush with the same depth reference as threshold/jambs.
    _snap(head, x=("min", 0.0), z=("min", jambs_top), y=("max", threshold_ymax))

    doc = App.newDocument("ThresholdJambAssembly")
    o1 = doc.addObject("Part::Feature", "Threshold");  o1.Shape = threshold
    o2 = doc.addObject("Part::Feature", "LeftJamb");   o2.Shape = left_jamb
    o3 = doc.addObject("Part::Feature", "RightJamb");  o3.Shape = right_jamb
    o4 = doc.addObject("Part::Feature", "Head");       o4.Shape = head
    doc.recompute()

    compound = Part.makeCompound([threshold, left_jamb, right_jamb, head])
    compound.exportStep(step_path)

    bb = compound.BoundBox
    print(f"OK compound bbox=({bb.XLength:.2f},{bb.YLength:.2f},{bb.ZLength:.2f}) "
          f"XMin={bb.XMin:.2f} XMax={bb.XMax:.2f} "
          f"YMin={bb.YMin:.2f} YMax={bb.YMax:.2f} "
          f"ZMin={bb.ZMin:.2f} ZMax={bb.ZMax:.2f}")
    print(f"threshold volume={threshold.Volume:.1f} "
          f"left_jamb volume={left_jamb.Volume:.1f} "
          f"right_jamb volume={right_jamb.Volume:.1f} "
          f"head volume={head.Volume:.1f}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
"""
    script = script.replace("__PARAMS_PATH__", params_path.replace("\\", "/"))

    script_path = os.path.join(tempfile.gettempdir(), "threshold_jamb_script.py")
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

    step_path = os.path.join(OUTPUT_DIR, "threshold_jamb_assembly.step")
    step_ok = export_combined_step(width_mm, height_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")


if __name__ == "__main__":
    main()