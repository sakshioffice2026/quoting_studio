"""
inspect_profile_source.py — READ-ONLY diagnostic.

Run from your project root (same place you run `python run.py`), with your
venv active:

    python inspect_profile_source.py 95

It prints, for Window id=95:
  - which ProfileSystem (if any) is pinned to the window
  - for each role (head, cill/threshold, jamb, mullion, transom), whether
    the bar/depth came from that pinned system's slot or from a role-default
    CadProfile fallback
  - the exact CadProfile DB row (id, code, name, bar_width_mm, depth_mm,
    role, is_role_default, is_active) behind each one

Does not modify any data. Does not touch model3d_freecad.py or
frame_assembly.py — it only calls the same public resolve_profiles()
function they already use, so what you see here is exactly what the
FreeCAD builder sees.
"""
import sys

WINDOW_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 95

# Same as run.py: load .env BEFORE importing create_app, so the real
# DATABASE_URL (not config.py's placeholder default) is used.
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.window import Window
from app.models.cad_profile import CadProfile
from app.services.frame_assembly import resolve_profiles, ROLE_FALLBACK

app = create_app()

with app.app_context():
    window = Window.query.get(WINDOW_ID)
    if window is None:
        print(f"No Window with id={WINDOW_ID} found.")
        sys.exit(1)

    print(f"Window id={window.id}  tenant_id={window.tenant_id}  "
          f"material={window.material}  unit_type={getattr(window, 'unit_type', 'window')}")
    print(f"profile_system_id={window.profile_system_id}")

    sys_obj = window.profile_system
    if sys_obj:
        print(f"Pinned ProfileSystem: id={sys_obj.id} name={getattr(sys_obj, 'name', '?')}")
        for slot in ('head', 'cill', 'threshold', 'jamb', 'mullion', 'transom'):
            prof = sys_obj.get_profile(slot)
            if prof:
                print(f"  slot={slot:10s} -> CadProfile id={prof.id} code={prof.code!r} "
                      f"name={prof.name!r} role={prof.role!r} "
                      f"bar_width_mm={prof.bar_width_mm} depth_mm={prof.depth_mm} "
                      f"is_role_default={getattr(prof, 'is_role_default', None)} "
                      f"is_active={getattr(prof, 'is_active', None)}")
            else:
                print(f"  slot={slot:10s} -> (empty, falls back to library role-default)")
    else:
        print("No ProfileSystem pinned — using library role-default CadProfile rows only.")

    print()
    print("Role-default / fallback CadProfile rows available for this tenant+material:")
    rows = (CadProfile.query
            .filter_by(tenant_id=window.tenant_id, material=window.material, is_active=True)
            .all())
    if not rows:
        rows = CadProfile.query.filter_by(tenant_id=window.tenant_id, is_active=True).all()
    for role in ('head', 'cill', 'threshold', 'jamb', 'mullion', 'transom'):
        candidates = [r for r in rows if r.role == role]
        for r in candidates:
            print(f"  role={role:10s} id={r.id} code={r.code!r} name={r.name!r} "
                  f"bar_width_mm={r.bar_width_mm} depth_mm={r.depth_mm} "
                  f"is_role_default={getattr(r, 'is_role_default', None)} "
                  f"is_active={r.is_active}")
        if not candidates:
            print(f"  role={role:10s} -> none found")

    print()
    print("Resolved ProfileSet actually handed to build_members() / the FreeCAD builder:")
    profiles = resolve_profiles(window.tenant_id, window.material, window=window)
    for role in ('head', 'cill', 'threshold', 'jamb', 'mullion', 'transom'):
        try:
            p = profiles.get(role)
        except Exception as exc:
            p = None
        if p:
            print(f"  role={role:10s} code={p.get('code')!r} bar={p.get('bar')} depth={p.get('depth')}")
        else:
            print(f"  role={role:10s} -> not resolved (None)")