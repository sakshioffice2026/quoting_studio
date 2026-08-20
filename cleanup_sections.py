"""Clean up codes/names for imported section profiles. Run from project root."""
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.cad_profile import CadProfile

TENANT_ID = 1  # <- adjust

# source_file -> (new_code, new_name)
CLEANUP = {
    'additional support(specific to l 20 door,l 20 door also has the standard additional support).dxf':
        ('SUP-L20', 'Additional Support (L20)'),
    'additional support.dxf':
        ('SUP-STD', 'Additional Support (Standard)'),
    'hinge between doors(specific for d 19 door).dxf':
        ('HNG-D19', 'Hinge Between Doors (D19)'),
    'interlocking part(2 specific for d19, d19 also has interlocking part 1)..dxf':
        ('ILK-D19-2', 'Interlocking Part 2 (D19)'),
    'lower base of door frame (part 1` specific to L16 door).dxf':
        ('LB-L16-1', 'Lower Base Door Frame Part 1 (L16)'),
    'lower base of door frame (part 2` specific to L16 door).dxf':
        ('LB-L16-2', 'Lower Base Door Frame Part 2 (L16)'),
    'lower base of door frame-1.dxf':
        ('LB-DOOR-1', 'Lower Base Door Frame (Alt)'),
    'lower base of door frame.dxf':
        ('LB-DOOR', 'Lower Base Door Frame'),
    'lower base specific to d19 door.dxf':
        ('LB-D19', 'Lower Base (D19)'),
    'parth in which glass is fitted(specific to door d 19).dxf':
        ('GB-D19', 'Glass Fit Part (D19)'),
    'partition between glass-1.dxf':
        ('PART-GLS-1', 'Partition Between Glass (Alt)'),
    'partition between glass.dxf':
        ('PART-GLS', 'Partition Between Glass'),
    'single door hinge.dxf':
        ('HNG-SGL', 'Single Door Hinge'),
    'spacer (specific to door D19 ).dxf':
        ('SPC-D19', 'Spacer (D19)'),
    'spacer (specific to door L16).dxf':
        ('SPC-L16', 'Spacer (L16)'),
    'spacers.dxf':
        ('SPC-STD', 'Spacer (Standard)'),
    'support in which glass is fitted.dxf':
        ('GB-STD', 'Glass Fit Support (Standard)'),
    'upper base of frame.dxf':
        ('HD-STD', 'Upper Base of Frame'),
    'lower base of frame.dxf':
        ('LB-D2', 'Lower Base of Frame (D2)'),
    'lower base support 1.dxf':
        ('LBS-D2-1', 'Lower Base Support 1 (D2)'),
    'lower base support 2.dxf':
        ('LBS-D2-2', 'Lower Base Support 2 (D2)'),
    'lower base support 3.dxf':
        ('LBS-D2-3', 'Lower Base Support 3 (D2)'),
    'partition between glass type 1.dxf':
        ('PART-GLS-D2-1', 'Partition Between Glass Type 1 (D2)'),
    'partition between glass type 2.dxf':
        ('PART-GLS-D2-2', 'Partition Between Glass Type 2 (D2)'),
    'supports perpendicular to the door height 1.dxf':
        ('SUP-D2-1', 'Support Perpendicular to Door Height 1 (D2)'),
    'supports perpendicular to the door height 2.dxf':
        ('SUP-D2-2', 'Support Perpendicular to Door Height 2 (D2)'),
    'supports perpendicular to the door height 3.dxf':
        ('SUP-D2-3', 'Support Perpendicular to Door Height 3 (D2)'),
}

def run():
    app = create_app()
    with app.app_context():
        updated = 0
        for source_file, (code, name) in CLEANUP.items():
            p = CadProfile.query.filter_by(
                tenant_id=TENANT_ID, source_file=source_file).first()
            if not p:
                print(f'SKIP (not found) {source_file}')
                continue
            p.code = code
            p.name = name
            updated += 1
            print(f'OK {source_file} -> {code} / {name}')
        db.session.commit()
        print(f'Updated {updated} profiles.')

if __name__ == '__main__':
    run()