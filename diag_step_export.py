"""
Standalone diagnostic — run directly with freecadcmd, no Flask/app code involved:

  & "D:\FreeCAD 1.1\bin\freecadcmd.exe" "D:\Quoting Studio\quoting_studio\diag_step_export.py"

This isolates whether STEP export is broken at the FreeCAD/OS level (a trivial
box also fails) or specific to our generated geometry (box works, real
assembly doesn't).
"""
import FreeCAD as App
import Part
import os

out_dir = r"D:\qs_freecad_tmp"
os.makedirs(out_dir, exist_ok=True)

doc = App.newDocument("Diag")

# --- Test 1: single trivial box, exported directly (no compound) ---
box = Part.makeBox(100, 100, 100)
print(f"box valid={box.isValid()} volume={box.Volume} faces={len(box.Faces)}")

p1 = os.path.join(out_dir, "diag_single_box.step")
Part.export([box], p1)
sz1 = os.path.getsize(p1)
print(f"TEST1 single box STEP: {sz1} bytes -> {p1}")

# --- Test 2: same box wrapped as a compound ---
comp = Part.makeCompound([box])
print(f"compound valid={comp.isValid()} volume={comp.Volume} subshapes={len(comp.SubShapes)}")

p2 = os.path.join(out_dir, "diag_compound_box.step")
Part.export([comp], p2)
sz2 = os.path.getsize(p2)
print(f"TEST2 compound box STEP: {sz2} bytes -> {p2}")

# --- Test 3: box added as a real document Part::Feature object first ---
feat = doc.addObject("Part::Feature", "Box1")
feat.Shape = box
doc.recompute()

p3 = os.path.join(out_dir, "diag_docobj_box.step")
Part.export([feat], p3)
sz3 = os.path.getsize(p3)
print(f"TEST3 doc-object box STEP: {sz3} bytes -> {p3}")

# --- Test 4: two boxes, offset, as raw shape list (mimics old broken code) ---
box2 = Part.makeBox(50, 50, 50)
box2.translate(App.Vector(200, 0, 0))
p4 = os.path.join(out_dir, "diag_two_boxes.step")
Part.export([box, box2], p4)
sz4 = os.path.getsize(p4)
print(f"TEST4 two-box raw list STEP: {sz4} bytes -> {p4}")

# --- Test 5: same two boxes, each as Part::Feature doc object (the fix) ---
feat_a = doc.addObject("Part::Feature", "MultiA")
feat_a.Shape = box
feat_b = doc.addObject("Part::Feature", "MultiB")
feat_b.Shape = box2
doc.recompute()
p5 = os.path.join(out_dir, "diag_multi_docobj.step")
Part.export([feat_a, feat_b], p5)
sz5 = os.path.getsize(p5)
print(f"TEST5 multi doc-object STEP: {sz5} bytes -> {p5}")

App.closeDocument(doc.Name)
print("DIAG_DONE")
print(f"SUMMARY: T1={sz1} T2={sz2} T3={sz3} T4={sz4} T5={sz5}")