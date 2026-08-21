"""Run from project root: python audit_cad_profiles.py
Checks every CadProfile row's bar_width_mm/depth_mm against the bbox of
its traced geometry_json. Flags rows where the stored values don't match
either orientation (real data error) or only match when swapped (same
class of bug fixed in engineering_dxf.py / model3d.py)."""
import json
from dotenv import load_dotenv
load_dotenv()
from app import create_app
from app.models.cad_profile import CadProfile

app = create_app()
with app.app_context():
    rows = CadProfile.query.filter(CadProfile.geometry_json.isnot(None)).all()
    print(f"Checking {len(rows)} profiles with traced geometry...\n")
    bad = 0
    for p in rows:
        try:
            loops = json.loads(p.geometry_json)
        except Exception:
            print(f"[{p.id}] {p.code}: geometry_json is not valid JSON"); bad += 1; continue
        allx = [x for lp in loops for x, y in lp]
        ally = [y for lp in loops for x, y in lp]
        if not allx or not ally:
            print(f"[{p.id}] {p.code}: empty geometry"); bad += 1; continue
        rx, ry = max(allx) - min(allx), max(ally) - min(ally)
        ref_bar, ref_dep = float(p.bar_width_mm), float(p.depth_mm)
        err_asis = abs(rx - ref_bar) + abs(ry - ref_dep)
        err_swap = abs(ry - ref_bar) + abs(rx - ref_dep)
        tol = 2.0  # mm
        if err_asis <= tol:
            continue  # matches, fine
        elif err_swap <= tol:
            print(f"[{p.id}] {p.code}: SWAPPED — DB says bar={ref_bar} depth={ref_dep}, "
                  f"traced geometry is bar={ry:.1f} depth={rx:.1f}")
            bad += 1
        else:
            print(f"[{p.id}] {p.code}: MISMATCH — DB says bar={ref_bar} depth={ref_dep}, "
                  f"traced bbox is {rx:.1f}x{ry:.1f} (doesn't match either orientation)")
            bad += 1
    print(f"\n{bad} of {len(rows)} profiles need review.")
