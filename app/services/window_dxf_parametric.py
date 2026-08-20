"""
Parametric window DXF generator — corrected frame, cill, and orthographic sections.
Matches fabrication standards with accurate coordinate geometry.

Input Parameters (all in mm):
  - Frame_Width, Frame_Height
  - Cill_Horn_Length (left/right overhang)
  - Cill_Nose_Depth (vertical projection below frame)
  - Frame_Profile_Thickness (wall thickness)
  - Section_Spacing (gap between elevation and side view)
"""

import io
import json
import logging
from datetime import date
from ezdxf.enums import TextEntityAlignment

logger = logging.getLogger(__name__)

# Default profile values
_DEFAULT_BAR = 40.0
_DEFAULT_WALL = 4.0
_DEFAULT_DEPTH = 52.0
_DEFAULT_REBATE = 20.0


def generate_parametric_window_dxf(window, panes, tenant_id=None, **params) -> bytes:
    """
    Generate parametric DXF with corrected cill and orthographic sections.
    
    Args:
        window: Window ORM object (width_mm, height_mm, design_json, etc.)
        panes: List of pane ORM objects
        tenant_id: Tenant ID for profile lookup
        **params: Override parameters:
            - cill_horn_length (mm)
            - cill_nose_depth (mm)
            - section_spacing (mm)
            - frame_profile_thickness (mm)
    
    Returns:
        UTF-8 encoded DXF bytes
    """
    try:
        import ezdxf
    except ImportError:
        logger.error('ezdxf not installed')
        return b''
    
    doc = ezdxf.new('R2010', setup=True)
    doc.units = 4
    
    # Setup
    from dxf_layers import setup_layers, setup_dimstyle, setup_text_styles
    setup_layers(doc)
    setup_dimstyle(doc)
    setup_text_styles(doc)
    
    msp = doc.modelspace()
    
    # Window dimensions
    W = float(window.width_mm)
    H = float(window.height_mm)
    
    # Profile
    profile = _get_profile(tenant_id, getattr(window, 'material', 'Aluminium'), window)
    bar = profile['bar']
    wall = profile['wall']
    depth = profile['depth']
    
    # Parametric overrides
    cill_horn = params.get('cill_horn_length', 40.0)
    cill_nose = params.get('cill_nose_depth', 30.0)
    sect_spacing = params.get('section_spacing', 300.0)
    frame_thickness = params.get('frame_profile_thickness', wall)
    
    # Parse design_json for pane layout
    panes_data = _parse_panes(window, panes)
    
    # === VIEW 1: ELEVATION (origin 0,0) ===
    _elevation(msp, W, H, bar, panes_data)
    
    # === CILL: Parametric below elevation ===
    from cill_geometry import draw_cill
    draw_cill(msp, W, cill_horn, cill_nose)
    
    # === VIEW 2: HORIZONTAL SECTION (plan strip) ===
    section_y = -(H * 0.45 + 300)
    _horizontal_section(msp, W, profile, section_y)
    
    # === VIEW 3: VERTICAL SECTION B-B (side view) ===
    # Task coordinate: Side Section X-Position = (X0 - Section_Spacing - Frame_Profile_Thickness)
    # With X0=0 (frame bottom-left origin), section positions to the left of elevation
    sect_x = -sect_spacing - frame_thickness
    from section_views import draw_vertical_section
    side_bottom_y = draw_vertical_section(
        msp, H, profile, sect_x, has_cill=bool(_get_cill_flag(window))
    )
    
    # === SCHEDULE TABLE ===
    _schedule(msp, W, H, panes_data, profile)
    
    # === DIMENSIONS & AUTO BOUNDING BOX ===
    bbox = _calculate_extents(W, H, sect_x, depth, cill_nose)
    _dimensions(msp, W, H, panes_data, section_y, sect_x, depth, bbox)
    
    # === TITLE BLOCK ===
    _titleblock(msp, window, profile, bbox, bar, section_y, side_bottom_y)
    
    # === SHEET BORDER ===
    _sheet_border(msp, bbox, bar)
    
    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode('utf-8')
    logger.info('Parametric DXF generated: %dx%d → %d bytes', int(W), int(H), len(data))
    return data


# ═══════════════════════════════════════════════════════════════
#  ELEVATION VIEW
# ═══════════════════════════════════════════════════════════════

def _elevation(msp, W, H, bar, panes_data):
    """Draw front elevation with frame, mullions, glass, and opener symbols."""
    # Outer frame
    msp.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 50}
    )
    
    # Mullions and transoms
    seen_x, seen_y = set(), set()
    
    for pane in panes_data:
        x_norm, y_norm, w_norm, h_norm, opening = pane
        
        # Vertical mullion
        rx = x_norm + w_norm
        if 0.001 < rx < 0.999 and round(rx, 3) not in seen_x:
            seen_x.add(round(rx, 3))
            mx = rx * W
            mullion_width = bar * 0.6
            msp.add_lwpolyline(
                [(mx - mullion_width/2, bar),
                 (mx + mullion_width/2, bar),
                 (mx + mullion_width/2, H - bar),
                 (mx - mullion_width/2, H - bar)],
                close=True,
                dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 35}
            )
        
        # Horizontal transom
        ty = y_norm + h_norm
        if 0.001 < ty < 0.999 and round(ty, 3) not in seen_y:
            seen_y.add(round(ty, 3))
            my = ty * H
            mullion_width = bar * 0.6
            msp.add_lwpolyline(
                [(bar, my - mullion_width/2),
                 (W - bar, my - mullion_width/2),
                 (W - bar, my + mullion_width/2),
                 (bar, my + mullion_width/2)],
                close=True,
                dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 35}
            )
        
        # Glass pane
        gx = x_norm * W + bar + 4
        gy = y_norm * H + bar + 4
        grx = (x_norm + w_norm) * W - bar - 4
        gry = (y_norm + h_norm) * H - bar - 4
        
        if grx > gx and gry > gy:
            msp.add_lwpolyline(
                [(gx, gy), (grx, gy), (grx, gry), (gx, gry)],
                close=True,
                dxfattribs={'layer': 'FRAME_GEOMETRY'}
            )
            
            # Opener symbol (swing lines)
            if opening and opening != 'Fixed':
                _draw_opener_symbol(msp, gx, gy, grx - gx, gry - gy, opening)


def _draw_opener_symbol(msp, x, y, w, h, opening):
    """Draw dashed swing arc for hinged/sliding openers."""
    d = {'layer': 'SWING_LINES', 'linetype': 'DASHED'}
    cx, cy = x + w/2, y + h/2
    
    if 'Left' in opening or opening == 'Casement':
        msp.add_line((x + w, y), (x + w*0.1, cy), dxfattribs=d)
        msp.add_line((x + w, y + h), (x + w*0.1, cy), dxfattribs=d)
    elif 'Right' in opening:
        msp.add_line((x, y), (x + w*0.9, cy), dxfattribs=d)
        msp.add_line((x, y + h), (x + w*0.9, cy), dxfattribs=d)
    elif 'Top' in opening:
        msp.add_line((x, y), (cx, y + h*0.9), dxfattribs=d)
        msp.add_line((x + w, y), (cx, y + h*0.9), dxfattribs=d)
    elif 'Slid' in opening:
        msp.add_line((x + w*0.15, cy), (x + w*0.85, cy), dxfattribs=d)


# ═══════════════════════════════════════════════════════════════
#  HORIZONTAL SECTION (PLAN STRIP)
# ═══════════════════════════════════════════════════════════════

def _horizontal_section(msp, W, profile, section_y):
    """Draw horizontal cross-section (plan view) through frame."""
    bar = profile['bar']
    depth = profile['depth']
    wall = profile['wall']
    
    section_h = depth + 40
    section_bot = section_y - section_h
    
    # Left and right jamb profile boxes (simplified)
    _draw_profile_box(msp, 0, section_bot, bar, depth, wall, section_y)
    _draw_profile_box(msp, W - bar, section_bot, bar, depth, wall, section_y, mirror=True)
    
    # Wall lines
    msp.add_line(
        (bar, section_y), (W - bar, section_y),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 20}
    )
    msp.add_line(
        (bar, section_bot), (W - bar, section_bot),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 20}
    )
    
    # Label
    msp.add_text(
        'HORIZONTAL SECTION A-A',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.5}
    ).set_placement((W/2, section_bot - bar*1.5), align=TextEntityAlignment.MIDDLE_CENTER)


def _draw_profile_box(msp, x, y_bot, w, depth, wall, y_top, mirror=False):
    """Draw a simplified hollow profile box."""
    layer = 'FRAME_GEOMETRY'
    
    # Outer
    msp.add_lwpolyline(
        [(x, y_bot), (x+w, y_bot), (x+w, y_top), (x, y_top)],
        close=True,
        dxfattribs={'layer': layer, 'lineweight': 25}
    )
    
    # Inner void
    msp.add_lwpolyline(
        [(x+wall, y_bot+wall), (x+w-wall, y_bot+wall),
         (x+w-wall, y_top-wall), (x+wall, y_top-wall)],
        close=True,
        dxfattribs={'layer': layer, 'lineweight': 15}
    )


# ═══════════════════════════════════════════════════════════════
#  SCHEDULE TABLE
# ═══════════════════════════════════════════════════════════════

def _schedule(msp, W, H, panes_data, profile):
    """Draw pane schedule table to the right of elevation."""
    bar = profile['bar']
    tx = W + bar * 5
    ty = H
    rh = bar * 0.8
    th = bar * 0.34
    col_w = [bar*1.2, bar*3.5, bar*3.5, bar*2.2]
    total_w = sum(col_w)
    n = len(panes_data) + 1
    
    # Outer border
    msp.add_lwpolyline(
        [(tx, ty), (tx+total_w, ty), (tx+total_w, ty-n*rh), (tx, ty-n*rh)],
        close=True,
        dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 35}
    )
    
    # Header row separator
    msp.add_line(
        (tx, ty - rh), (tx + total_w, ty - rh),
        dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 20}
    )
    
    # Column dividers
    cx = tx
    headers = ['#', 'Opener', 'Glazing', 'Size']
    for i, hdr in enumerate(headers):
        if i > 0:
            msp.add_line(
                (cx, ty - n*rh), (cx, ty),
                dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 15}
            )
        msp.add_text(
            hdr,
            dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': th}
        ).set_placement((cx + col_w[i]*0.5, ty - rh*0.45), align=TextEntityAlignment.MIDDLE_CENTER)
        cx += col_w[i]
    
    # Data rows
    for r_idx, pane in enumerate(panes_data):
        x_norm, y_norm, w_norm, h_norm, opening = pane
        ry = ty - (r_idx + 2) * rh
        
        msp.add_line(
            (tx, ry), (tx + total_w, ry),
            dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 10}
        )
        
        w_mm = int(round(w_norm * W))
        h_mm = int(round(h_norm * H))
        vals = [str(r_idx+1), opening or 'Fixed', 'DGU', f'{w_mm}×{h_mm}']
        
        cx = tx
        for i, val in enumerate(vals):
            msp.add_text(
                val,
                dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': th*0.9}
            ).set_placement((cx + col_w[i]*0.5, ry + rh*0.35), align=TextEntityAlignment.MIDDLE_CENTER)
            cx += col_w[i]


# ═══════════════════════════════════════════════════════════════
#  DIMENSIONS & BOUNDING BOX
# ═══════════════════════════════════════════════════════════════

def _calculate_extents(W, H, sect_x, depth, cill_nose):
    """Auto-calculate geometry bounding box."""
    bar = 40.0  # approximate
    
    x_min = -bar * 4  # dim space left
    x_max = sect_x + depth * 3 + bar * 5
    y_min = -cill_nose - bar * 5  # cill extends below
    y_max = H + bar * 4
    
    return {'x_min': x_min, 'x_max': x_max, 'y_min': y_min, 'y_max': y_max}


def _dimensions(msp, W, H, panes_data, section_y, sect_x, depth, bbox):
    """Draw overall and pane dimensions."""
    layer_dim = 'DIMENSIONS'
    
    # Overall width — above elevation
    msp.add_line(
        (-50, H + 120), (W + 50, H + 120),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_line(
        (-50, H + 100), (-50, H + 120),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_line(
        (W + 50, H + 100), (W + 50, H + 120),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_text(
        f'{W:.0f}',
        dxfattribs={'layer': layer_dim, 'height': 30}
    ).set_placement((W/2, H + 140), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Overall height — right of section
    msp.add_line(
        (sect_x + depth*3.5, 0), (sect_x + depth*3.5, H),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_line(
        (sect_x + depth*3.3, 0), (sect_x + depth*3.5, 0),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_line(
        (sect_x + depth*3.3, H), (sect_x + depth*3.5, H),
        dxfattribs={'layer': layer_dim, 'lineweight': 15}
    )
    msp.add_text(
        f'{H:.0f}',
        dxfattribs={'layer': layer_dim, 'height': 30}
    ).set_placement((sect_x + depth*3.8, H/2), align=TextEntityAlignment.MIDDLE_CENTER)


def _sheet_border(msp, bbox, bar):
    """Draw sheet border around all content."""
    margin = bar * 4
    
    x0 = bbox['x_min'] - margin
    x1 = bbox['x_max'] + margin
    y0 = bbox['y_min'] - margin
    y1 = bbox['y_max'] + margin
    
    # Outer border
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 50}
    )
    
    # Inner margin line
    m2 = bar * 0.8
    msp.add_lwpolyline(
        [(x0+m2, y0+m2), (x1-m2, y0+m2),
         (x1-m2, y1-m2), (x0+m2, y1-m2)],
        close=True,
        dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 20}
    )


# ═══════════════════════════════════════════════════════════════
#  TITLE BLOCK
# ═══════════════════════════════════════════════════════════════

def _titleblock(msp, window, profile, bbox, bar, section_y, side_bottom_y):
    """Draw title block with drawing info."""
    tb_h = bar * 8
    tb_y1 = min(section_y, side_bottom_y if side_bottom_y else section_y) - bar * 3
    tb_y0 = tb_y1 - tb_h
    
    bx0 = bbox['x_min'] - bar * 2
    bx1 = bbox['x_max'] + bar * 2
    bw = bx1 - bx0
    
    # Border
    msp.add_lwpolyline(
        [(bx0, tb_y0), (bx1, tb_y0), (bx1, tb_y1), (bx0, tb_y1)],
        close=True,
        dxfattribs={'layer': 'BORDER_LAYOUT', 'lineweight': 40}
    )
    
    # Company name
    company = getattr(window.project.tenant, 'name', 'QUOTING STUDIO') if hasattr(window, 'project') else 'QUOTING STUDIO'
    msp.add_text(
        company.upper(),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': tb_h*0.2}
    ).set_placement((bx0 + bw*0.1, tb_y0 + tb_h*0.6), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Drawing info
    w_mm = int(window.width_mm)
    h_mm = int(window.height_mm)
    info_text = f'Window {w_mm}×{h_mm}mm | {profile["name"]}'
    
    msp.add_text(
        info_text,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': tb_h*0.15}
    ).set_placement((bx0 + bw*0.35, tb_y0 + tb_h*0.5), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Drawing number & date
    drw_no = f'QS-{getattr(window, "id", "?")}'
    date_str = date.today().strftime('%d/%m/%Y')
    
    msp.add_text(
        f'Drw: {drw_no}',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': tb_h*0.12}
    ).set_placement((bx1 - bw*0.15, tb_y0 + tb_h*0.6), align=TextEntityAlignment.MIDDLE_RIGHT)
    
    msp.add_text(
        f'Date: {date_str}',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': tb_h*0.12}
    ).set_placement((bx1 - bw*0.15, tb_y0 + tb_h*0.3), align=2)


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _get_profile(tenant_id, material, window=None):
    """Load profile parameters. Priority:
       1. window.profile_system_id -> ProfileSystem (same resolution used
          by the STEP/3D pipeline in frame_assembly.resolve_profiles)
       2. tenant's is_default=True CadProfile for this material
       3. hardcoded fallback
    """
    prof = {
        'bar': _DEFAULT_BAR,
        'wall': _DEFAULT_WALL,
        'depth': _DEFAULT_DEPTH,
        'rebate': _DEFAULT_REBATE,
        'name': 'PWQ-3645',
        'ref': 'PWQ-3645'
    }
    
    if not tenant_id:
        return prof
    
    try:
        from app.models.cad_profile import CadProfile
        from app.models.profile_system import ProfileSystem

        p = None

        sys_id = getattr(window, 'profile_system_id', None) if window else None
        if sys_id:
            psys = ProfileSystem.query.get(sys_id)
            if psys:
                slot_id = psys.head_id or psys.jamb_id or psys.cill_id
                if slot_id:
                    p = CadProfile.query.get(slot_id)

        if p is None:
            p = (CadProfile.query
                 .filter_by(tenant_id=tenant_id, material=material, is_active=True, is_default=True)
                 .first() or
                 CadProfile.query.filter_by(tenant_id=tenant_id, is_active=True).first())
        
        if p:
            prof.update(
                bar=float(p.bar_width_mm),
                wall=float(p.wall_thickness_mm),
                depth=float(p.depth_mm),
                rebate=float(p.glass_rebate_mm),
                name=p.name,
                ref=p.drawing_ref or 'CUSTOM'
            )
    except Exception as exc:
        logger.warning('Profile lookup failed: %s', exc)
    
    return prof


def _get_cill_flag(window):
    """Extract cill.enabled from design_json."""
    try:
        if getattr(window, 'design_json', None):
            design = json.loads(window.design_json)
            frame_cfg = design.get('frame', {}) or {}
            return frame_cfg.get('cill', False)
    except Exception as exc:
        logger.warning('Could not parse design_json: %s', exc)
    return False


def _parse_panes(window, panes):
    """Extract pane geometry from ORM objects."""
    panes_data = []
    
    for p in panes:
        x_norm = getattr(p, 'x_norm', 0.0)
        y_norm = getattr(p, 'y_norm', 0.0)
        w_norm = getattr(p, 'w_norm', 1.0)
        h_norm = getattr(p, 'h_norm', 1.0)
        opener = getattr(p, 'opener_type', 'Fixed')
        
        panes_data.append((x_norm, y_norm, w_norm, h_norm, opener))
    
    return panes_data if panes_data else [(0.0, 0.0, 1.0, 1.0, 'Fixed')]