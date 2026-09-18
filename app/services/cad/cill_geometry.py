"""
Parametric cill (sill) geometry module.

Corrected coordinate logic:
  Frame Bottom-Left = (0, 0)
  Cill Bottom-Left = (-Cill_Horn_Length, -Cill_Nose_Depth)
  Cill Top spans from (-Cill_Horn_Length, 0) to (Frame_Width + Cill_Horn_Length, 0)
  
The cill is drawn on the WINDOW_CILL layer (Yellow/2) with higher visual weight.
"""
import ezdxf
from ezdxf.enums import TextEntityAlignment


def draw_cill(msp, frame_width, horn_length=40.0, nose_depth=30.0, cill_height=20.0):
    """
    Draw a parametric projecting cill board below the frame.
    
    Args:
        msp: ezdxf modelspace
        frame_width: Total frame width (mm)
        horn_length: Left/right overhang extension (mm) — default 40mm
        nose_depth: Vertical depth/projection below frame (mm) — default 30mm
        cill_height: Height of the cill board profile (mm) — default 20mm
    
    Coordinate System:
        Frame sits at Y=0 (bottom-left origin)
        Cill bottom-left = (-horn_length, -nose_depth)
        Cill extends horizontally from X = -horn_length to X = frame_width + horn_length
    """
    
    # ─────────────────────────────────────────────────────────────────
    # VALIDATE before drawing — clamp invalid horn/nose values so we
    # never emit self-intersecting or negative-width geometry.
    # ─────────────────────────────────────────────────────────────────
    check = verify_cill_geometry(frame_width, horn_length, nose_depth)
    if not check['valid']:
        import logging
        logging.getLogger(__name__).warning(
            'Invalid cill geometry, clamping: %s', '; '.join(check['errors']))
        horn_length = max(0.0, min(horn_length, frame_width * 0.5))
        nose_depth = max(0.0, nose_depth)

    # ─────────────────────────────────────────────────────────────────
    # MAIN CILL BODY (rectangular projection below frame)
    # ─────────────────────────────────────────────────────────────────
    
    # Outer boundary
    cill_x0 = -horn_length
    cill_x1 = frame_width + horn_length
    cill_y0 = -nose_depth
    cill_y1 = 0.0  # Top edge of cill aligns with frame bottom
    
    # Draw main cill rectangle
    pts_main = [
        (cill_x0, cill_y0),
        (cill_x1, cill_y0),
        (cill_x1, cill_y1),
        (cill_x0, cill_y1)
    ]
    
    msp.add_lwpolyline(
        pts_main,
        close=True,
        dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 50, 'color': 2}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # CILL PROFILE DETAIL (realistic wedge/drip groove)
    # ─────────────────────────────────────────────────────────────────
    
    # Drip groove near outer (front) edge — prevents water runoff
    drip_y = cill_y0 + nose_depth * 0.35
    msp.add_line(
        (cill_x0, drip_y),
        (cill_x1, drip_y),
        dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 25, 'color': 2}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # HORN ENDS (end-return vertical edges where cill projects beyond frame)
    # ─────────────────────────────────────────────────────────────────
    
    # Left horn vertical edge
    msp.add_line(
        (cill_x0, cill_y0),
        (cill_x0, cill_y1),
        dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 50, 'color': 2}
    )
    
    # Right horn vertical edge
    msp.add_line(
        (cill_x1, cill_y0),
        (cill_x1, cill_y1),
        dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 50, 'color': 2}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # INTERNAL NOSE DETAIL (transition from frame to cill body)
    # ─────────────────────────────────────────────────────────────────
    
    # Seam line where cill meets the frame bottom bar (Y=0)
    msp.add_line(
        (cill_x0, cill_y1),
        (cill_x1, cill_y1),
        dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 40, 'color': 2}
    )
    
    # Optional: internal vertical stiffener lines (for visual stability)
    # Placed at the horn edges to emphasize the structural support
    stiffener_inset = horn_length * 0.2
    for stiff_x in (cill_x0 + stiffener_inset, cill_x1 - stiffener_inset):
        if cill_x0 < stiff_x < cill_x1:
            msp.add_line(
                (stiff_x, cill_y0),
                (stiff_x, drip_y),
                dxfattribs={'layer': 'WINDOW_CILL', 'lineweight': 15, 'color': 2,
                           'linetype': 'CONTINUOUS'}
            )
    
    # ─────────────────────────────────────────────────────────────────
    # ANNOTATIONS
    # ─────────────────────────────────────────────────────────────────
    
    # Cill label (centered at bottom-left overhang midpoint)
    label_x = frame_width / 2
    label_y = cill_y0 - nose_depth * 0.15
    
    msp.add_text(
        'CILL',
        dxfattribs={'layer': 'WINDOW_CILL', 'height': 30, 'color': 2}
    ).set_placement((label_x, label_y), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Horn length annotation (dimension callout)
    msp.add_text(
        f'{horn_length:.0f}mm horn each side',
        dxfattribs={'layer': 'WINDOW_CILL', 'height': 20, 'color': 8}
    ).set_placement((label_x, label_y - nose_depth*0.2), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Nose depth annotation (vertical dimension)
    msp.add_text(
        f'{nose_depth:.0f}mm depth',
        dxfattribs={'layer': 'WINDOW_CILL', 'height': 18, 'color': 8}
    ).set_placement((cill_x0 - horn_length*0.5, -nose_depth/2), align=TextEntityAlignment.BOTTOM_RIGHT)


def draw_cill_section_profile(msp, x0, y0, depth_s, bar_s, wall_s, lip_s, bar):
    """
    Cross-sectional view of the projecting cill for vertical (side) section.
    Used in Section B-B (vertical/side view).
    
    Args:
        msp: ezdxf modelspace
        x0, y0: Base position (bottom-left of section)
        depth_s: Scaled profile depth
        bar_s: Scaled bar width
        wall_s: Scaled wall thickness
        lip_s: Scaled lip extension (horn equivalent in cross-section)
        bar: Unscaled bar width (for text sizing)
    
    Returns:
        Y-coordinate of cill top surface (glass rests on this line)
    """
    
    cill_h = bar_s * 0.55  # Cill profile height (slimmer than main frame bar)
    
    # Exterior overhang extends outward (negative X direction from nominal section position)
    ox0 = x0 - lip_s  # Outer (front) edge with overhang
    ox1 = x0 + depth_s  # Inner (back) edge
    
    # Vertical extent
    oy0 = y0  # Bottom edge
    oy1 = y0 + cill_h  # Top edge (glass support surface)
    
    # Small upstand at the interior/glass edge (prevents glass sliding)
    upstand = cill_h * 0.35
    
    # ─────────────────────────────────────────────────────────────────
    # CILL SECTION OUTLINE (trapezoidal or compound profile)
    # ─────────────────────────────────────────────────────────────────
    
    pts = [
        (ox0, oy0),  # Bottom-left (exterior/front)
        (ox1, oy0),  # Bottom-right (interior/back)
        (ox1, oy1 + upstand),  # Top-right with upstand
        (ox0, oy1)  # Top-left (sloped or stepped)
    ]
    
    msp.add_lwpolyline(
        pts,
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 35, 'color': 2}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # DRIP GROOVE (detail line in cross-section)
    # ─────────────────────────────────────────────────────────────────
    
    drip_y = oy0 + cill_h * 0.3
    msp.add_line(
        (ox0, drip_y),
        (ox1, drip_y),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18, 'color': 2}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # GLASS LINE (sits on top of cill)
    # ─────────────────────────────────────────────────────────────────
    
    msp.add_line(
        (ox0, oy1),
        (ox1, oy1),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 25, 'color': 2,
                   'linetype': 'CONTINUOUS'}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # CILL LABEL
    # ─────────────────────────────────────────────────────────────────
    
    label_x = ox0 + (ox1 - ox0) / 2
    msp.add_text(
        'CILL PROFILE',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.34, 'color': 2}
    ).set_placement((label_x, oy0 - bar*0.55), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # ─────────────────────────────────────────────────────────────────
    # RETURN TOP SURFACE Y-COORDINATE (for glass placement in main view)
    # ─────────────────────────────────────────────────────────────────
    
    return oy1


def verify_cill_geometry(frame_width, horn_length, nose_depth):
    """
    Verify parametric cill dimensions are sensible.
    
    Returns:
        dict with coordinates and validation status
    """
    errors = []
    
    if frame_width <= 0:
        errors.append(f'frame_width must be positive, got {frame_width}')
    if horn_length < 0:
        errors.append(f'horn_length must be non-negative, got {horn_length}')
    if nose_depth < 0:
        errors.append(f'nose_depth must be non-negative, got {nose_depth}')
    
    if horn_length > frame_width * 0.5:
        errors.append(f'horn_length ({horn_length}mm) exceeds half frame width ({frame_width/2}mm)')
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'cill_x_min': -horn_length,
        'cill_x_max': frame_width + horn_length,
        'cill_y_min': -nose_depth,
        'cill_y_max': 0.0,
        'cill_total_width': frame_width + 2*horn_length,
        'cill_total_depth': nose_depth
    }
