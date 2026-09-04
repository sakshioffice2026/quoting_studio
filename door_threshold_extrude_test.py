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

Axis convention (FIX — was wrong before):
  The source DXF (lower base of door frame.dxf) is digitised with:
    local-X (165 mm) = bar face width across the door opening
    local-Y  (60 mm) = depth through the wall

  Correct FreeCAD mapping for a horizontal member in the YZ plane,
  extruded along +X (door/window width):
    world-Y = local-Y = 60 mm   (through-wall depth)
    world-Z = local-X = 165 mm  (bar face height in elevation)
  => V(0.0, float(y), float(x))   <- note y,x order (not x,y)

  Previous code used V(0.0, float(x), float(y)) which put 165 mm
  through the wall -- 75 mm deeper than the jamb (90 mm) and head
  (90 mm), making the threshold project far beyond the wall cavity
  in the top-view STEP.

Sanity-check after fix:
  STEP bounding box must be (length_mm, 60.00, 165.00).
  YLength=60 mm (through wall), ZLength=165 mm (elevation face height).
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

    # NOTE: this string is an f-string only for injecting params_path and step_path.
    # All FreeCAD-side variables (bb, y_ok, z_ok) must use {{ }} to escape the outer
    # f-string, and ternary expressions on FreeCAD variables must be written as
    # plain string concatenation with + so Python never tries to evaluate them at
    # build time on the host side.
    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

try:
    data = json.load(open(r"{params_path}", encoding="utf-8"))
    pts_2d = data["points"]
    L = float(data["length_mm"])
    step_path = data["step_path"]

    # Profile lies in the YZ plane at X=0; extrude along +X (door width).
    #
    # PITCH FIX (90deg about world-X): the flat base must sit
    # horizontally on the ground plane, rising UP into the dam — not
    # standing the profile on its edge. That means:
    #   world-Z (height, floor to dam top) = local-y (0..60 mm)
    #   world-Y (exterior<->interior footprint) = local-x (0..165 mm)
    # This is the opposite pairing from the previous version, which
    # put the 165 mm span vertical (Z) and stood the profile on edge.

    # ---- ORIENTATION (exterior drainage ramp vs. interior dam) -----
    # local-y already rises correctly with no mirror needed: ramp
    # points sit at low y (near the floor), the dam/upstand sits at
    # high y (rises toward the top) — that ordering IS "up", so
    # world-Z = local-y directly.
    #
    # The exterior/interior split is now on local-x instead: classify
    # every point by which side of the x-midpoint it falls on, then
    # compare each group's average x — computed from the actual data
    # every run, not a hardcoded index range.
    x_vals = [float(x) for x, _ in pts_2d]
    y_vals = [float(y) for _, y in pts_2d]
    x_mid = (min(x_vals) + max(x_vals)) / 2.0
    ramp_xs = [x for x in x_vals if x <= x_mid]
    dam_xs  = [x for x in x_vals if x > x_mid]
    ramp_avg = sum(ramp_xs) / len(ramp_xs) if ramp_xs else 0.0
    dam_avg  = sum(dam_xs) / len(dam_xs) if dam_xs else 0.0

    # EXTERIOR_AT_Y_MIN: exterior (ramp) sits at the low-Y end,
    # interior (dam) sits at the high-Y end — matching the Y-min=0
    # "back/exterior reference" convention used for the other frame
    # members. Flip this constant if the exterior face should instead
    # be at high-Y for this assembly.
    EXTERIOR_AT_Y_MIN = True

    x_extent = max(x_vals) - min(x_vals)
    currently_ramp_at_min = ramp_avg <= dam_avg
    needs_mirror = currently_ramp_at_min != EXTERIOR_AT_Y_MIN

    def _oriented_y(x):
        x0 = float(x) - min(x_vals)  # normalise to start at 0
        return (x_extent - x0) if needs_mirror else x0

    def _floor_up_z(y):
        return float(y) - min(y_vals)  # normalise so base sits at Z=0

    # => V(0.0, oriented_y(x), floor_up_z(y))
    pts = [V(0.0, _oriented_y(x), _floor_up_z(y)) for x, y in pts_2d]
    pts.append(pts[0])
    wire = Part.makePolygon(pts)
    if not wire.isClosed():
        raise RuntimeError("profile wire not closed")
    face = Part.Face(wire)
    if not face.isValid() or face.Area <= 1.0:
        raise RuntimeError("invalid/degenerate face, area=" + str(face.Area))

    solid = face.extrude(V(L, 0.0, 0.0))
    if not solid.isValid() or solid.Volume <= 1.0:
        raise RuntimeError("invalid/empty extrude, volume=" + str(solid.Volume))

    doc = App.newDocument("ThresholdTest")
    obj = doc.addObject("Part::Feature", "DoorThreshold")
    obj.Shape = solid
    doc.recompute()

    solid.exportStep(step_path)
    bb = solid.BoundBox

    # Expected after pitch fix: XLength=length_mm, YLength=165, ZLength=60.
    # Use plain string concatenation — ternary on bb.* cannot be inside
    # the outer f-string or Python evaluates it on the host at build time.
    y_ok = abs(bb.YLength - 165.0) < 0.5
    z_ok = abs(bb.ZLength - 60.0) < 0.5
    print("OK bbox=(" + str(round(bb.XLength,2)) + "," +
          str(round(bb.YLength,2)) + "," + str(round(bb.ZLength,2)) +
          ") volume=" + str(round(solid.Volume,1)))
    print("  YLength (ext<->int footprint): " + str(round(bb.YLength,2)) +
          " mm  " + ("PASS (expected 165)" if y_ok else "FAIL (expected 165)"))
    print("  ZLength (floor-up height):     " + str(round(bb.ZLength,2)) +
          " mm  " + ("PASS (expected 60)" if z_ok else "FAIL (expected 60)"))

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
    print(f"Profile bbox (as digitised): {maxx - minx:.2f} x {maxy - miny:.2f} mm "
          f"(local-X=165 across bar face, local-Y=60 through wall)")
    print(f"Expected STEP bbox after fix: {length_mm:.0f} x 165.00 x 60.00 mm "
          f"(X=length, Y=165 ext<->int footprint, Z=60 floor-up height)")

    step_path = os.path.join(OUTPUT_DIR, "threshold_test.step")
    dxf_path  = os.path.join(OUTPUT_DIR, "threshold_section.dxf")

    step_ok = export_step(length_mm, step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")

    dxf_ok = export_dxf(dxf_path)
    print(f"DXF export:  {'OK -> ' + dxf_path if dxf_ok else 'FAILED'}")


if __name__ == "__main__":
    main()