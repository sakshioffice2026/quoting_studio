"""Bulk-import DXF sections into CadProfile. Run from project root."""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.cad_profile import CadProfile
from app.services.dxf_parser import process_dxf
SECTIONS_DIR = 'import_data/Sections'   # matches your folder

TENANT_ID = 1                            # <- adjust tenant id
MATERIAL = 'Aluminium'                   # <- adjust material

# filename keyword -> (role, category)
ROLE_MAP = [
    ('upper base of frame',        ('head', 'Frame')),
    ('lower base of door frame',   ('threshold', 'Frame')),
    ('lower base of frame',        ('threshold', 'Frame')),
    ('lower base support',         ('threshold', 'Frame')),
    ('lower base',                 ('threshold', 'Frame')),
    ('spacer',                     ('coupler', 'Hardware')),
    ('interlocking part',          ('mullion', 'Mullion')),
    ('hinge',                      (None, 'Hardware')),
    ('partition between glass',    ('glazing_bead', 'GlazingBead')),
    ('parth in which glass',       ('glazing_bead', 'GlazingBead')),
    ('support in which glass',     ('glazing_bead', 'GlazingBead')),
    ('supports perpendicular',     ('mullion', 'Mullion')),
    ('additional support',         ('mullion', 'Mullion')),
]

def guess_role(fname):
    low = fname.lower()
    for key, val in ROLE_MAP:
        if key in low:
            return val
    return (None, 'Frame')

def code_from_filename(fname):
    base = os.path.splitext(fname)[0]
    return base[:30]

def run():
    app = create_app()
    with app.app_context():
        count = 0
        for root, _, files in os.walk(SECTIONS_DIR):
            for fname in files:
                if not fname.lower().endswith('.dxf') or fname.lower().endswith('.bak.dxf'):
                    continue
                path = os.path.join(root, fname)
                with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                    content = fh.read()
                result = process_dxf(content)
                if not result.get('ok'):
                    print(f'SKIP (parse error) {fname}: {result.get("error")}')
                    continue
                role, category = guess_role(fname)
                profile = CadProfile(
                    tenant_id=TENANT_ID,
                    code=code_from_filename(fname),
                    name=os.path.splitext(fname)[0],
                    category=category,
                    material=MATERIAL,
                    role=role,
                    is_builtin=False,
                    geometry_json=result['geometry_json'],
                    svg_path=result['svg_path'],
                    vertex_count=result['vertex_count'],
                    source_file=fname,
                    bar_width_mm=result.get('width_mm', 40.0),
                    depth_mm=result.get('height_mm', 52.0),
                )
                db.session.add(profile)
                count += 1
                print(f'OK {fname} -> role={role}')
        db.session.commit()
        print(f'Imported {count} profiles.')

if __name__ == '__main__':
    run()