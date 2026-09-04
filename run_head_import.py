"""
Run this from the project root to import head.dxf into the database:

    python run_head_import.py

Change TENANT_ID and MATERIAL below to match your data before running.
"""
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.services.head_profile_dxf_import import import_head_profile

TENANT_ID = 1
MATERIAL = "Aluminium"

app = create_app()
with app.app_context():
    row = import_head_profile(tenant_id=TENANT_ID, material=MATERIAL, commit=True)
    if row is None:
        print("Import FAILED — see WARNING/ABORT message above.")
    else:
        print(f"Import OK — CadProfile id={row.id}, code={row.code}, "
              f"vertex_count={row.vertex_count}, source_file={row.source_file}")