"""
Example usage: Parametric Window DXF Generator with corrected geometry.

This script demonstrates:
1. How to call the parametric DXF generator
2. How to override default cill and section parameters
3. How to verify geometry before generating DXF
4. Integration with existing Flask/SQLAlchemy ORM objects
"""

from window_dxf_parametric import generate_parametric_window_dxf
from cill_geometry import verify_cill_geometry
from section_views import verify_section_alignment


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 1: Basic usage with default parameters
# ═════════════════════════════════════════════════════════════════

def example_basic(window_orm_object, panes_list, tenant_id):
    """
    Generate DXF with default parametric values.
    
    Default Parameters:
      - cill_horn_length = 40mm (left/right overhang)
      - cill_nose_depth = 30mm (vertical projection)
      - section_spacing = 300mm (gap from elevation to side view)
    """
    dxf_bytes = generate_parametric_window_dxf(
        window=window_orm_object,
        panes=panes_list,
        tenant_id=tenant_id
    )
    return dxf_bytes


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 2: Custom cill parameters
# ═════════════════════════════════════════════════════════════════

def example_custom_cill(window_orm_object, panes_list, tenant_id):
    """
    Override cill dimensions for a specific project requirement.
    
    This example uses:
      - Larger horn overhang (50mm instead of default 40mm)
      - Deeper nose projection (45mm instead of default 30mm)
    """
    dxf_bytes = generate_parametric_window_dxf(
        window=window_orm_object,
        panes=panes_list,
        tenant_id=tenant_id,
        cill_horn_length=50.0,      # Override: 50mm horns
        cill_nose_depth=45.0        # Override: 45mm nose depth
    )
    return dxf_bytes


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 3: Custom section spacing (for larger windows)
# ═════════════════════════════════════════════════════════════════

def example_large_window_with_spacing(window_orm_object, panes_list, tenant_id):
    """
    For large windows, increase spacing between elevation and side view
    so the drawing doesn't look crowded.
    """
    W = float(window_orm_object.width_mm)
    H = float(window_orm_object.height_mm)
    
    # Proportional section spacing: 1/3 of frame width
    section_spacing = W * 0.33
    
    dxf_bytes = generate_parametric_window_dxf(
        window=window_orm_object,
        panes=panes_list,
        tenant_id=tenant_id,
        section_spacing=section_spacing
    )
    return dxf_bytes


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 4: Validation before generation (recommended)
# ═════════════════════════════════════════════════════════════════

def example_with_validation(window_orm_object, panes_list, tenant_id,
                           cill_horn=40.0, cill_nose=30.0, section_gap=300.0):
    """
    Validate geometry parameters before DXF generation.
    Ensures all dimensions are sensible and within manufacturing limits.
    """
    W = float(window_orm_object.width_mm)
    H = float(window_orm_object.height_mm)
    
    # Check cill geometry validity
    cill_check = verify_cill_geometry(W, cill_horn, cill_nose)
    if not cill_check['valid']:
        print(f"❌ Cill geometry errors:")
        for error in cill_check['errors']:
            print(f"   - {error}")
        return None  # Abort generation
    
    print(f"✓ Cill geometry valid:")
    print(f"  Total cill width: {cill_check['cill_total_width']:.0f}mm")
    print(f"  Cill extents: X=[{cill_check['cill_x_min']:.0f}, {cill_check['cill_x_max']:.0f}]")
    print(f"  Cill depth: {cill_check['cill_total_depth']:.0f}mm")
    
    # Check section alignment
    section_check = verify_section_alignment(W, H, section_gap)
    if not section_check['valid']:
        print(f"❌ Section geometry errors:")
        for error in section_check['errors']:
            print(f"   - {error}")
        return None  # Abort generation
    
    print(f"✓ Section alignment valid:")
    print(f"  Vertical section X position: {section_check['section_x_position']:.0f}mm")
    print(f"  Section Y-aligned at: {section_check['section_y_aligned_at']:.0f}mm")
    
    # Generate DXF
    dxf_bytes = generate_parametric_window_dxf(
        window=window_orm_object,
        panes=panes_list,
        tenant_id=tenant_id,
        cill_horn_length=cill_horn,
        cill_nose_depth=cill_nose,
        section_spacing=section_gap
    )
    
    print(f"✓ DXF generated: {len(dxf_bytes)} bytes")
    return dxf_bytes


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 5: Flask route integration (existing codebase)
# ═════════════════════════════════════════════════════════════════

def example_flask_route_integration():
    """
    Example Flask route handler that replaces the existing
    `generate_window_dxf()` call with the parametric version.
    
    Usage in your Flask app:
        from flask import Blueprint, request, send_file
        from models.window import Window
        from models.pane import Pane
        
        dxf_bp = Blueprint('dxf', __name__)
        
        @dxf_bp.route('/api/window/<window_id>/dxf', methods=['GET'])
        def get_window_dxf(window_id):
            window = Window.query.get(window_id)
            if not window:
                return {'error': 'Window not found'}, 404
            
            panes = Pane.query.filter_by(window_id=window_id).all()
            tenant_id = window.project.tenant_id if window.project else None
            
            # Extract parameters from query string
            cill_horn = request.args.get('cill_horn_length', 40.0, type=float)
            cill_nose = request.args.get('cill_nose_depth', 30.0, type=float)
            sect_gap = request.args.get('section_spacing', 300.0, type=float)
            
            # Generate with validation
            dxf_data = example_with_validation(
                window, panes, tenant_id,
                cill_horn=cill_horn,
                cill_nose=cill_nose,
                section_gap=sect_gap
            )
            
            if dxf_data is None:
                return {'error': 'Invalid geometry parameters'}, 400
            
            return send_file(
                io.BytesIO(dxf_data),
                mimetype='application/vnd.dxf',
                as_attachment=True,
                download_name=f'window-{window_id}.dxf'
            )
    """
    pass


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 6: Batch processing (generate DXF for multiple windows)
# ═════════════════════════════════════════════════════════════════

def example_batch_process(window_list, tenant_id):
    """
    Process multiple windows in a project, generating DXF for each.
    Demonstrates iteration with consistent parameters.
    """
    results = []
    
    for window in window_list:
        try:
            panes = window.panes  # Assume ORM relationship exists
            
            dxf_bytes = generate_parametric_window_dxf(
                window=window,
                panes=panes,
                tenant_id=tenant_id,
                cill_horn_length=40.0,
                cill_nose_depth=30.0,
                section_spacing=300.0
            )
            
            results.append({
                'window_id': window.id,
                'status': 'success',
                'size_bytes': len(dxf_bytes),
                'dxf_data': dxf_bytes
            })
            
        except Exception as exc:
            results.append({
                'window_id': window.id,
                'status': 'failed',
                'error': str(exc)
            })
    
    return results


# ═════════════════════════════════════════════════════════════════
# EXAMPLE 7: Project-specific parameter profiles
# ═════════════════════════════════════════════════════════════════

class ProjectParameterProfile:
    """
    Store project-level parameter presets to avoid repetitive
    parameter specification.
    """
    
    PROFILES = {
        'standard_uk': {
            'cill_horn_length': 40.0,
            'cill_nose_depth': 30.0,
            'section_spacing': 300.0,
            'frame_profile_thickness': 4.0,
            'description': 'Standard UK fabrication parameters'
        },
        'large_commercial': {
            'cill_horn_length': 50.0,
            'cill_nose_depth': 40.0,
            'section_spacing': 400.0,
            'frame_profile_thickness': 5.0,
            'description': 'Large commercial / institutional windows'
        },
        'heritage_replication': {
            'cill_horn_length': 35.0,
            'cill_nose_depth': 25.0,
            'section_spacing': 250.0,
            'frame_profile_thickness': 3.5,
            'description': 'Heritage restoration / period-accurate'
        },
        'minimal_overhang': {
            'cill_horn_length': 20.0,
            'cill_nose_depth': 20.0,
            'section_spacing': 250.0,
            'frame_profile_thickness': 4.0,
            'description': 'Flush / minimal cill projection'
        }
    }
    
    @classmethod
    def get_profile(cls, profile_name):
        """Retrieve a named parameter profile."""
        return cls.PROFILES.get(profile_name, cls.PROFILES['standard_uk'])
    
    @classmethod
    def apply_to_window(cls, window, panes, tenant_id, profile_name='standard_uk'):
        """Generate DXF using a named profile."""
        params = cls.get_profile(profile_name)
        
        return generate_parametric_window_dxf(
            window=window,
            panes=panes,
            tenant_id=tenant_id,
            **{k: v for k, v in params.items() if k != 'description'}
        )


# ═════════════════════════════════════════════════════════════════
# QUICK TEST / MINIMAL MOCK
# ═════════════════════════════════════════════════════════════════

class MockWindow:
    """Minimal mock for testing without database."""
    def __init__(self, width_mm=1200, height_mm=1500, label='Test Window'):
        self.id = 1
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.label = label
        self.material = 'Aluminium'
        self.frame_colour_name = 'White'
        self.design_json = '{"frame": {"cill": true}}'
        self.project = None


class MockPane:
    """Minimal mock pane for testing."""
    def __init__(self, x_norm=0, y_norm=0, w_norm=1, h_norm=1, opener='Fixed'):
        self.x_norm = x_norm
        self_norm = y_norm
        self.w_norm = w_norm
        self.h_norm = h_norm
        self.opener_type = opener
        self.glazing_type = 'DGU'


def quick_test():
    """
    Quick test using mock objects (no database required).
    """
    print("Starting quick test...")
    
    # Create mock objects
    window = MockWindow(width_mm=1200, height_mm=1500)
    panes = [
        MockPane(x_norm=0, y_norm=0, w_norm=0.5, h_norm=1, opener='Left Casement'),
        MockPane(x_norm=0.5, y_norm=0, w_norm=0.5, h_norm=1, opener='Right Casement')
    ]
    
    # Validate parameters
    print("\n--- Geometry Validation ---")
    W = float(window.width_mm)
    cill_check = verify_cill_geometry(W, cill_horn=40.0, cill_nose=30.0)
    print(f"Cill valid: {cill_check['valid']}")
    if not cill_check['valid']:
        print(f"Errors: {cill_check['errors']}")
    
    # Generate DXF
    print("\n--- Generating DXF ---")
    try:
        dxf_bytes = example_with_validation(
            window, panes, tenant_id=None,
            cill_horn=40.0, cill_nose=30.0, section_gap=300.0
        )
        
        if dxf_bytes:
            # Save to file
            with open('/tmp/test_window.dxf', 'wb') as f:
                f.write(dxf_bytes)
            print(f"✓ DXF saved to /tmp/test_window.dxf")
        else:
            print("✗ DXF generation failed")
    except Exception as exc:
        print(f"✗ Exception: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    # Uncomment to run mock test:
    # quick_test()
    
    # Or use with real ORM objects:
    # from models.window import Window
    # from models.pane import Pane
    # window = Window.query.get(123)
    # panes = Pane.query.filter_by(window_id=123).all()
    # dxf = example_with_validation(window, panes, tenant_id=1)
    
    print(__doc__)
