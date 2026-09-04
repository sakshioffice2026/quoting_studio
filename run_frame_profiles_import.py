"""
Run this from the project root to import jamb.dxf (role="jamb") and
sill.dxf (role="threshold") into the database:

    python run_frame_profiles_import.py

Change TENANT_ID and MATERIAL below to match your data before running.
"""
import os

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.services.head_profile_dxf_import import import_profile

TENANT_ID = 1
MATERIAL = "Aluminium"

_SECTIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "app", "cad_sections", "cad_sections",
)

TARGETS = [
    ("jamb",      os.path.join(_SECTIONS_DIR, "jamb.dxf")),
    ("threshold", os.path.join(_SECTIONS_DIR, "sill.dxf")),
]

app = create_app()
with app.app_context():
    for role, dxf_path in TARGETS:
        row = import_profile(tenant_id=TENANT_ID, role=role,
                              material=MATERIAL, dxf_path=dxf_path,
                              commit=True)
        if row is None:
            print(f"[{role}] Import FAILED — see WARNING/ABORT message above.")
        else:
            print(f"[{role}] Import OK — CadProfile id={row.id}, "
                  f"code={row.code}, vertex_count={row.vertex_count}, "
                  f"source_file={row.source_file}")
