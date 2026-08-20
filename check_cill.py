import os
os.chdir('D:\\Quoting Studio\\quoting_studio')

import sys
sys.path.insert(0, '.')

from app import create_app
app = create_app()

with app.app_context():
    from app.models.cad_profile import CadProfile
    profiles = CadProfile.query.filter(CadProfile.role.like('%cill%')).all()
    print(f'Cill profiles found: {len(profiles)}')
    for p in profiles:
        print(f'  id={p.id} code={p.code} name={p.name} role={p.role} material={p.material} is_active={p.is_active} is_default={p.is_default}')
    
    # Also check all profiles
    all_profiles = CadProfile.query.all()
    print(f'\nTotal CadProfiles: {len(all_profiles)}')
    for p in all_profiles:
        print(f'  id={p.id} code={p.code} name={p.name} role={p.role} material={p.material}')