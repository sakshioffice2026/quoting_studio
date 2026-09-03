"""
Run from project root:
    python frame_assembly_flat_slab.py

Standalone check ONLY — NOT wired into frame_assembly.py / model3d.py /
model3d_freecad.py. NOT the verified traced-profile assembly (see
frame_assembly_test.py) — this is a simplified flat-slab picture-frame
representation, per explicit request, extruded uniformly along Z.

WARNING: this discards the real traced threshold/head/jamb profiles
(53/18/66 points) and their own individual member depths in favor of
a single uniform slab depth. Bar thicknesses below are NOT invented —
they reuse each member's own real traced depth extent (from
threshold_geometry.py / head_geometry.py / jamb_geometry.py bboxes) as
a stand-in for elevation-view bar thickness, since no elevation
bar-thickness value was supplied in the spec. Confirm before treating
this output as engineering-accurate.

Fixed per explicit spec:
    Total Width  (X): 1160 mm
    Total Height (Y): 880 mm
    Total Depth  (Z): 165 mm  (uniform extrusion depth, all parts)

Placement (front elevation on XY plane, extrude +Z):
    Threshold : X 0..1160,    Y 0..60      (bar = threshold's real depth, 60mm)
    Head      : X 0..1160,    Y 845..880   (bar = head's real depth, 35mm)
    Jamb L    : X 0..90,      Y 0..880     (bar = jamb's real depth, 90mm)
    Jamb R    : X 1070..1160, Y 0..880
    All parts : Z 0..165

Output: output/frame_assembly_flat_slab.step
"""
import sys
import os
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

W_TOTAL = 1160.0
H_TOTAL = 880.0
Z_DEPTH = 165.0

THRESHOLD_BAR = 60.0   # threshold_geometry.py bbox depth
HEAD_BAR = 35.0        # head_geometry.py bbox depth
JAMB_BAR = 90.0        # jamb_geometry.py bbox depth


def _find_freecad():
    from app.services.model3d_freecad import _find_freecad as ff
    return ff()


def export_flat_slab_step(step_path: str):
    freecad = _find_freecad()
    if not freecad:
        print("FreeCAD not found — skipping STEP export. "
              "Set FREECAD_CMD env var or install FreeCAD.")
        return False

    params_path = os.path.join(tempfile.gettempdir(), "flat_slab_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({
            "W": W_TOTAL, "H": H_TOTAL, "Z": Z_DEPTH,
            "threshold_bar": THRESHOLD_BAR, "head_bar": HEAD_BAR,
            "jamb_bar": JAMB_BAR, "step_path": step_path,
        }, f)

    script = f'''
import FreeCAD as App, Part, json, traceback, sys
V = App.Vector

try:
    data = json.load(open(r"{params_path}", encoding="utf-8"))
    W = float(data["W"]); H = float(data["H"]); Z = float(data["Z"])
    tb = float(data["threshold_bar"]); hb = float(data["head_bar"])
    jb = float(data["jamb_bar"]); step_path = data["step_path"]

    threshold  = Part.makeBox(W, tb, Z, V(0.0, 0.0, 0.0))
    head       = Part.makeBox(W, hb, Z, V(0.0, H - hb, 0.0))
    jamb_left  = Part.makeBox(jb, H, Z, V(0.0, 0.0, 0.0))
    jamb_right = Part.makeBox(jb, H, Z, V(W - jb, 0.0, 0.0))

    for name, solid in [("Threshold", threshold), ("Head", head),
                         ("JambLeft", jamb_left), ("JambRight", jamb_right)]:
        if not solid.isValid() or solid.Volume <= 1.0:
            raise RuntimeError(f"invalid/empty {{name}}, volume={{solid.Volume}}")

    doc = App.newDocument("FlatSlabAssembly")
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
    print(f"threshold volume={{threshold.Volume:.1f}} head volume={{head.Volume:.1f}} "
          f"jamb_left volume={{jamb_left.Volume:.1f}} jamb_right volume={{jamb_right.Volume:.1f}}")
except Exception:
    print("SCRIPT_ERROR")
    traceback.print_exc(file=sys.stdout)
'''
    script_path = os.path.join(tempfile.gettempdir(), "flat_slab_script.py")
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Flat-slab assembly: W={W_TOTAL} H={H_TOTAL} Z-depth={Z_DEPTH}")

    step_path = os.path.join(OUTPUT_DIR, "frame_assembly_flat_slab.step")
    step_ok = export_flat_slab_step(step_path)
    print(f"STEP export: {'OK -> ' + step_path if step_ok else 'FAILED'}")


if __name__ == "__main__":
    main()