"""
Run from project root:
    python frame_assembly_test.py [width_mm] [height_mm]

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py.

Conventions:
  - threshold: (x,y) -> V(0,x,y-depth), extrude +X by width_mm.
               Back face flush at Z=0 (depth=60mm, so front face at
               Z=-60). No Y-translate (nests at bottom).
  - head:      (x,y) -> V(0,x,y-depth), extrude +X by width_mm.
               Back face flush at Z=0 (depth=35mm, so front face at
               Z=-35) — same Z=0 back-face reference as threshold,
               instead of both sharing a Z=0 front face. Translate
               +(H - head_y_extent) on Y (nests at top).
  - jamb:      (u,v) -> V(sign*v, 0, u), extrude +Y by height_mm.
               Rotated 90 deg about Y from the previous u->X, v->Z
               mapping: depth (v) now runs along world X, across (u)
               along world Z — matches frame_section_assembly.py's 2D
               jamb rotation.
               Left jamb (sign=-1): depth extends in -X, outside the
               frame opening.
               Right jamb (sign=+1): depth extends in +X, then
               translate +X by width_mm.
  - after all four members are built, apply ONE rigid-body +90 degree
    rotation about world X to the COMPLETE assembly:
        X -> X, Y -> Z, Z -> -Y
    so the final frame lies in the vertical XZ plane:
        X = width, Z = height, Y = profile depth.
    Member geometry and relative placement are unchanged.

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
    get_head_bbox, get_profile_points_normalised as head_pts,
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

    minx, miny, maxx, maxy = get_head_bbox()
    head_y_extent = maxx - minx

    params_path = os.path.join(tempfile.gettempdir(), "frame_assembly_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold_pts": threshold_pts(),
            "head_pts": head_pts(),
            "jamb_pts": jamb_pts(),
            "width_mm": width_mm,
            "height_mm": height_mm,
            "head_y_extent": head_y_extent,
            "step_path": step_path,
        }, f)

    script = """
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

def _extrude_horizontal(pts_2d, length, reference_depth):
    # DEPTH-ALIGNMENT FIX (assumption — not confirmed against a spec,
    # see chat): exterior/weather face is treated as the shared
    # reference plane. All members' FRONT face aligns at the same
    # depth (reference_depth = jamb's 90mm), interior/back face
    # recesses by each member's own depth difference. Previously every
    # member's BACK face was flush at Z=0 instead, leaving front faces
    # staggered (threshold 60mm, head 35mm, jamb 90mm) with no shared
    # reference at all.
    pts = [V(0.0, float(x), float(y) - reference_depth) for x, y in pts_2d]
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

def _extrude_vertical(pts_2d, length, flip_x=False):
    # FIX: previous code mapped v (depth, 90mm) to world-X, which made
    # each jamb stick out 90mm beyond the frame width on its own side
    # (matches the +90/-90mm bug seen in the reported bbox: X range
    # was -90..1090 instead of 0..1000 for width_mm=1000).
    #
    # Correct mapping per reference drawing (jambs nest WITHIN the
    # overall frame width, not beyond it):
    #   u (across profile, 67mm — the jamb's own face width) -> world-X
    #   v (depth through wall, 90mm) -> world-Z (becomes final depth
    #     after the assembly's +90deg rotation), back face flush at
    #     Z=0 same convention as threshold/head.
    u_extent = max(float(u) for u, _ in pts_2d)   # 67mm face width
    v_extent = max(float(v) for _, v in pts_2d)   # 90mm depth
    sign = -1.0 if flip_x else 1.0
    # flip_x mirrors the profile for handedness (left vs right jamb are
    # typically mirror-image parts) AND must be re-offset by u_extent so
    # the mirrored profile still lands in [0, u_extent], not [-u_extent, 0].
    x_offset = u_extent if flip_x else 0.0
    pts = [V(sign * float(u) + x_offset, 0.0, float(v) - v_extent) for u, v in pts_2d]
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
    return solid, u_extent

try:
    data = json.load(open(r"__PARAMS_PATH__", encoding="utf-8"))
    threshold_pts   = data["threshold_pts"]
    head_pts        = data["head_pts"]
    jamb_pts        = data["jamb_pts"]
    W               = float(data["width_mm"])
    H               = float(data["height_mm"])
    head_y_extent   = float(data["head_y_extent"])
    step_path       = data["step_path"]

    # Jamb depth (90mm) is the shared exterior-face reference for all
    # three member types — see _extrude_horizontal fix note above.
    jamb_v_extent = max(float(v) for _, v in jamb_pts)

    threshold = _extrude_horizontal(threshold_pts, W, jamb_v_extent)

    head = _extrude_horizontal(head_pts, W, jamb_v_extent)
    head.translate(V(0.0, H - head_y_extent, 0.0))

    # NESTED convention (per reference drawing: overall frame width W
    # already includes the jambs — jambs sit at the two ends of the
    # threshold/head span, not beyond it).
    jamb_left, jamb_w = _extrude_vertical(jamb_pts, H, flip_x=True)

    jamb_right, _ = _extrude_vertical(jamb_pts, H, flip_x=False)
    jamb_right.translate(V(W - jamb_w, 0.0, 0.0))

    # -------------------------------------------------------------
    # ONE rigid-body transform for the COMPLETE ASSEMBLY.
    #
    # The four solids above are already generated with their actual
    # traced profiles and their intended relative positions.
    # Do NOT rotate/rebuild individual members here.
    #
    # +90 degrees about X:
    #     X' = X
    #     Y' = Z
    #     Z' = -Y
    #
    # Final CAD convention:
    #     X = frame width
    #     Y = profile depth
    #     Z = frame height
    # -------------------------------------------------------------
    for solid in (
        threshold,
        head,
        jamb_left,
        jamb_right,
    ):
        solid.rotate(
            V(0.0, 0.0, 0.0),
            V(1.0, 0.0, 0.0),
            90.0,
        )

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