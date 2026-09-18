import FreeCAD as App

# EDIT this to your exact .fcstd filename (run `dir *.fcstd` in that folder
# to confirm the exact name/parentheses/spacing first).
path = r"D:\Quoting Studio\quoting_studio\QS-W93 (1).fcstd"

doc = App.openDocument(path)

for name in ("Shape2DView", "Shape2DView001", "Shape2DView002"):
    obj = doc.getObject(name)
    if obj is None:
        print(f"{name}: NOT FOUND")
        continue
    bb = obj.Shape.BoundBox
    pl = obj.Placement
    ang = pl.Rotation.Angle * 180.0 / 3.14159265358979
    axis = pl.Rotation.Axis
    print(f"{obj.Label} ({name})")
    print(f"  Placement.Base = ({pl.Base.x:.3f}, {pl.Base.y:.3f}, {pl.Base.z:.3f})")
    print(f"  Rotation = {ang:.2f} deg about ({axis.x:.2f},{axis.y:.2f},{axis.z:.2f})")
    print(f"  BoundBox = X[{bb.XMin:.3f}, {bb.XMax:.3f}]  Y[{bb.YMin:.3f}, {bb.YMax:.3f}]")
    print()

App.closeDocument(doc.Name)