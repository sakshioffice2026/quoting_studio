import sys
sys.path.insert(0, 'app/services')
from window_dxf_parametric import generate_parametric_window_dxf
from cill_geometry import verify_cill_geometry
from section_views import verify_section_alignment

# Create a mock window object
class MockWindow:
    def __init__(self, width_mm=1200, height_mm=1500):
        self.id = 1
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.material = 'Aluminium'
        self.design_json = '{"frame": {"cill": true}}'
        self.project = type('Proj', (), {'tenant': type('Tenant', (), {'name': 'TEST TENANT'})})()

class MockPane:
    def __init__(self, x_norm=0, y_norm=0, w_norm=1, h_norm=1, opener='Fixed'):
        self.x_norm = x_norm
        self.y_norm = y_norm
        self.w_norm = w_norm
        self.h_norm = h_norm
        self.opener_type = opener

window = MockWindow(width_mm=1200, height_mm=1500)
panes = [MockPane(x_norm=0, y_norm=0, w_norm=0.5, h_norm=1, opener='Left Casement')]

# Validate geometry
W = float(window.width_mm)
H = float(window.height_mm)
cill_check = verify_cill_geometry(W, 40.0, 30.0)
print(f'Cill valid: {cill_check["valid"]}')
if not cill_check['valid']:
    for e in cill_check['errors']:
        print(f'  Error: {e}')

section_check = verify_section_alignment(W, H, 300.0)
print(f'Section valid: {section_check["valid"]}')
if not section_check['valid']:
    for e in section_check['errors']:
        print(f'  Error: {e}')

# Generate DXF
print('\nGenerating DXF...')
dxf_bytes = generate_parametric_window_dxf(
    window=window,
    panes=panes,
    tenant_id=None,
    cill_horn_length=40.0,
    cill_nose_depth=30.0,
    section_spacing=300.0,
    frame_profile_thickness=4.0
)

if dxf_bytes:
    print(f'✓ DXF generated successfully: {len(dxf_bytes)} bytes')
    with open('/tmp/test_window_fixed.dxf', 'wb') as f:
        f.write(dxf_bytes)
    print(f'✓ DXF saved to /tmp/test_window_fixed.dxf')
else:
    print('✗ DXF generation failed')