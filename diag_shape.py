"""
Run on the SERVER, from the project root:
    python diag_shape.py <window_id>

Checks the 3 things that cause "still rectangle": missing file,
wrong design_json, and stale bytecode.
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

wid = int(sys.argv[1]) if len(sys.argv) > 1 else None

print("1) FILE CHECK")
for f in ("app/services/arch_geometry.py",
          "app/services/frame_assembly.py",
          "app/services/model3d.py"):
    print(f"   {f}: {'FOUND' if os.path.isfile(f) else 'MISSING'}")

print("2) arch_geometry FUNCTIONS")
try:
    from app.services import arch_geometry
    print("   loaded from:", arch_geometry.__file__)
    print("   has circular_outline:", hasattr(arch_geometry, "circular_outline"))
except Exception as exc:
    print("   IMPORT FAILED:", exc)

if wid:
    print(f"3) WINDOW {wid} design_json")
    from app import create_app
    from app.models import Window
    app = create_app()
    with app.app_context():
        w = Window.query.get(wid)
        if not w:
            print("   window not found")
        else:
            print("   window.shape column:", getattr(w, "shape", None))
            design = json.loads(w.design_json or "{}")
            print("   design_json.shape:", design.get("shape"))
            print("   design_json.archRise:", design.get("archRise"))

            from app.services import frame_assembly
            asm = frame_assembly.build_members(w, [])
            for m in asm.members:
                print("   member", m.id, "path_pts=",
                      len(m.path) if m.path else 0, "closed=", m.closed)
else:
    print("3) pass a window id to test build_members on a real record:")
    print("   python diag_shape.py 123")
