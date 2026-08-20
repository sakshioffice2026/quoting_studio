from ezdxf.enums import TextEntityAlignment

"""
Orthographic section views (A-A horizontal, B-B vertical) with Y-coordinate alignment.

Coordinate Rules:
  - Elevation origin = (0, 0) at frame bottom-left
  - Horizontal Section A-A: Y-coordinates ALIGNED with elevation (same Y = same height)
  - Vertical Section B-B: X-positioned at (frame_width + section_spacing),
    Y-coordinates aligned with elevation (Y=0 at bottom, Y=H at top)
"""


def draw_vertical_section(msp, frame_height, profile, sect_x, has_cill=False):
    """
    Draw vertical cross-section (side view) through HEAD and CILL/SILL.
    Section B-B: aligned orthographically with elevation.
    
    Args:
        msp: ezdxf modelspace
        frame_height: Window height (mm)
        profile: Dict with {bar, wall, depth, rebate, name, ref}
        sect_x: X-position of section (frame_width + section_spacing)
        has_cill: If True, draw projecting cill detail; else plain sill
    
    Returns:
        Lowest Y reached by section geometry (for sheet extent calculation)
    """
    
    bar = profile['bar']
    wall = profile['wall']
    depth = profile['depth']
    rebate = profile['rebate']
    scale = 3.0  # Section compression ratio
    
    bar_s = bar * scale
    wall_s = wall * scale
    depth_s = depth * scale
    reb_s = rebate * scale
    
    # ─────────────────────────────────────────────────────────────────
    # HEAD PROFILE (top of window)
    # Y = frame_height down to Y = frame_height - bar_s
    # ─────────────────────────────────────────────────────────────────
    
    # Mirror = True so the profile faces the correct direction (inward)
    ty0 = frame_height - bar_s  # head bottom
    ty1 = frame_height  # head top
    
    _draw_profile_section(
        msp, sect_x, ty0, depth_s, bar_s, wall_s, reb_s,
        mirror=True, label_y=frame_height + bar*0.5
    )
    
    # ─────────────────────────────────────────────────────────────────
    # GAP BETWEEN HEAD AND SILL (represents the glass span)
    # ─────────────────────────────────────────────────────────────────
    
    gap = bar_s * 2.0  # Fixed proportional gap (not full window height)
    
    # ─────────────────────────────────────────────────────────────────
    # SILL / CILL PROFILE (bottom of window)
    # ─────────────────────────────────────────────────────────────────
    
    by1 = gap  # Sill top (relative to section origin)
    by0 = by1 - bar_s  # Sill bottom (nominal)
    
    if has_cill:
        # Import cill section drawing function
        from cill_geometry import draw_cill_section_profile
        lip_s = 40.0 * scale
        cill_top = draw_cill_section_profile(
            msp, sect_x, by0, depth_s, bar_s, wall_s, lip_s, bar
        )
        by1 = cill_top  # Glass sits on cill top surface
        section_bottom = by0 - bar_s * 0.5  # Cill extends further down
    else:
        # Plain sill (mirrored profile)
        _draw_profile_section(
            msp, sect_x, by0, depth_s, bar_s, wall_s, reb_s,
            mirror=False, label_y=by0 - bar*1.5
        )
        section_bottom = by0 - bar_s * 0.3
    
    # ─────────────────────────────────────────────────────────────────
    # GLASS UNIT (double glazing panes)
    # Stacked vertically between head and sill, with spacer bar
    # ─────────────────────────────────────────────────────────────────
    
    gc_x = sect_x + depth_s / 2  # Glass centerline (horizontal)
    gy1 = by1 + reb_s * 0.4  # Glass bottom (sits on sill rebate)
    gy2 = ty0 - reb_s * 0.4  # Glass top (sits in head rebate)
    pane_gap = depth_s * 0.18  # Gap between outer and inner pane
    
    # Draw two vertical glass lines (outer and inner pane edges)
    for gx in (gc_x - pane_gap/2, gc_x + pane_gap/2):
        msp.add_line(
            (gx, gy1), (gx, gy2),
            dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
        )
    
    # Spacer bar at bottom of glass unit
    msp.add_lwpolyline(
        [(gc_x - pane_gap/2, gy1),
         (gc_x - pane_gap/2, gy1 + depth_s*0.05),
         (gc_x + pane_gap/2, gy1 + depth_s*0.05),
         (gc_x + pane_gap/2, gy1)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
    )
    
    # Spacer bar at top of glass unit
    msp.add_lwpolyline(
        [(gc_x - pane_gap/2, gy2),
         (gc_x - pane_gap/2, gy2 - depth_s*0.05),
         (gc_x + pane_gap/2, gy2 - depth_s*0.05),
         (gc_x + pane_gap/2, gy2)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # SECTION LABEL & PROFILE INFO
    # ─────────────────────────────────────────────────────────────────
    
    label_x = sect_x + depth_s / 2
    
    msp.add_text(
        'VERTICAL SECTION B-B',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.55}
    ).set_placement((label_x, section_bottom - bar*1.4), align=TextEntityAlignment.MIDDLE_CENTER)
    
    msp.add_text(
        f'PROFILE: {profile["ref"]} | {bar:.0f}mm FRAME | {wall:.0f}mm WALL | {depth:.0f}mm DEPTH',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.34}
    ).set_placement((label_x, section_bottom - bar*2.2), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # ─────────────────────────────────────────────────────────────────
    # DIMENSION CALLOUTS (head and sill heights)
    # ─────────────────────────────────────────────────────────────────
    
    dim_x = sect_x + depth_s + bar*0.6
    
    # Head dimension
    msp.add_line(
        (dim_x, ty0), (dim_x, ty1),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_line(
        (dim_x - bar*0.3, ty0), (dim_x, ty0),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_line(
        (dim_x - bar*0.3, ty1), (dim_x, ty1),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_text(
        f'{bar_s/scale:.0f}',
        dxfattribs={'layer': 'DIMENSIONS', 'height': 25}
    ).set_placement((dim_x + bar*0.4, (ty0 + ty1)/2), align=TextEntityAlignment.MIDDLE_CENTER)
    
    # Sill dimension
    msp.add_line(
        (dim_x, by0), (dim_x, by1),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_line(
        (dim_x - bar*0.3, by0), (dim_x, by0),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_line(
        (dim_x - bar*0.3, by1), (dim_x, by1),
        dxfattribs={'layer': 'DIMENSIONS', 'lineweight': 15}
    )
    msp.add_text(
        f'{bar_s/scale:.0f}',
        dxfattribs={'layer': 'DIMENSIONS', 'height': 25}
    ).set_placement((dim_x + bar*0.4, (by0 + by1)/2), align=TextEntityAlignment.MIDDLE_CENTER)
    
    return section_bottom


def _draw_profile_section(msp, x, y, width, height, wall, rebate, mirror=False, label_y=None):
    """
    Draw a hollow rectangular profile section (used in vertical B-B view).
    
    Args:
        msp: ezdxf modelspace
        x, y: Bottom-left corner position
        width: Horizontal extent (depth of frame in section)
        height: Vertical extent (bar width)
        wall: Wall thickness (hollow chamber inset)
        rebate: Glazing rebate dimension
        mirror: If True, reverses rebate orientation (for head vs. sill)
        label_y: Y position for label (optional)
    """
    
    # Outer profile rectangle
    msp.add_lwpolyline(
        [(x, y), (x+width, y), (x+width, y+height), (x, y+height)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 35}
    )
    
    # Inner void (hollow chamber)
    msp.add_lwpolyline(
        [(x+wall, y+wall),
         (x+width-wall, y+wall),
         (x+width-wall, y+height-wall),
         (x+wall, y+height-wall)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
    )
    
    # Glazing rebate (leg pointing toward glass)
    if not mirror:
        # Rebate on right side (sill)
        leg_x = x + width - wall
    else:
        # Rebate on left side (head)
        leg_x = x + wall
    
    # Highlight the rebate as a slightly thicker line
    msp.add_line(
        (leg_x, y),
        (leg_x, y + height),
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 20}
    )
    
    # Optional label
    if label_y is not None:
        label_x = x + width / 2
        profile_type = 'HEAD' if mirror else 'SILL'
        msp.add_text(
            profile_type,
            dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': 20}
        ).set_placement((label_x, label_y), align=TextEntityAlignment.MIDDLE_CENTER)


def draw_horizontal_section(msp, frame_width, profile, section_y):
    """
    Draw horizontal cross-section (plan strip) through frame jambs.
    Section A-A: shows left and right frame profiles side-by-side.
    
    Args:
        msp: ezdxf modelspace
        frame_width: Window width (mm)
        profile: Dict with {bar, wall, depth, rebate, name, ref}
        section_y: Y-position of section top edge
    
    Returns:
        Y-coordinate of section bottom edge
    """
    
    bar = profile['bar']
    wall = profile['wall']
    depth = profile['depth']
    rebate = profile['rebate']
    
    section_h = depth + 40
    section_bot = section_y - section_h
    
    # ─────────────────────────────────────────────────────────────────
    # LEFT JAMB PROFILE (X = 0 to X = bar)
    # ─────────────────────────────────────────────────────────────────
    
    _draw_profile_section_horizontal(
        msp, 0, section_bot, bar, depth, wall, rebate,
        mirror=False
    )
    
    # ─────────────────────────────────────────────────────────────────
    # RIGHT JAMB PROFILE (mirrored, X = frame_width - bar to X = frame_width)
    # ─────────────────────────────────────────────────────────────────
    
    _draw_profile_section_horizontal(
        msp, frame_width - bar, section_bot, bar, depth, wall, rebate,
        mirror=True
    )
    
    # ─────────────────────────────────────────────────────────────────
    # GLASS SPAN (gap between jambs)
    # ─────────────────────────────────────────────────────────────────
    
    glass_x1 = bar - rebate * 0.4
    glass_x2 = frame_width - bar + rebate * 0.4
    gc_y = section_bot + depth / 2
    pane_gap = depth * 0.18
    
    # Two vertical glass panes (front and back)
    for gy in (gc_y - pane_gap/2, gc_y + pane_gap/2):
        msp.add_line(
            (glass_x1, gy), (glass_x2, gy),
            dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
        )
    
    # Spacer bar (aluminum) between panes
    msp.add_lwpolyline(
        [(glass_x1 + 8, gc_y - pane_gap/2),
         (glass_x1 + 8 + depth*0.05, gc_y - pane_gap/2),
         (glass_x1 + 8 + depth*0.05, gc_y + pane_gap/2),
         (glass_x1 + 8, gc_y + pane_gap/2)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 18}
    )
    
    # ─────────────────────────────────────────────────────────────────
    # SECTION LABEL
    # ─────────────────────────────────────────────────────────────────
    
    msp.add_text(
        'HORIZONTAL SECTION A-A',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.5}
    ).set_placement((frame_width/2, section_bot - bar*1.4), align=TextEntityAlignment.MIDDLE_CENTER)
    
    msp.add_text(
        f'PROFILE: {profile["ref"]} | {bar:.0f}mm FRAME | {wall:.0f}mm WALL | {depth:.0f}mm DEPTH',
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'height': bar*0.34}
    ).set_placement((frame_width/2, section_bot - bar*2.2), align=TextEntityAlignment.MIDDLE_CENTER)
    
    return section_bot


def _draw_profile_section_horizontal(msp, x, y, width, depth, wall, rebate, mirror=False):
    """
    Draw a hollow rectangular profile for horizontal (plan) section.
    
    Args:
        msp: ezdxf modelspace
        x, y: Bottom-left corner (Y is the section's lower boundary)
        width: Horizontal extent (bar width)
        depth: Vertical extent in the section (profile depth into wall)
        wall: Wall thickness
        rebate: Glazing rebate dimension
        mirror: If True, reverses the orientation
    """
    
    # Outer profile
    msp.add_lwpolyline(
        [(x, y), (x+width, y), (x+width, y+depth), (x, y+depth)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 25}
    )
    
    # Inner void
    msp.add_lwpolyline(
        [(x+wall, y+wall),
         (x+width-wall, y+wall),
         (x+width-wall, y+depth-wall),
         (x+wall, y+depth-wall)],
        close=True,
        dxfattribs={'layer': 'FRAME_GEOMETRY', 'lineweight': 15}
    )
    
    # Hatch (indicates solid aluminum)
    try:
        h = msp.add_hatch(color=1, dxfattribs={'layer': 'FRAME_GEOMETRY'})
        h.set_solid_fill(color=1)
        h.paths.add_polyline_path(
            [(x, y), (x+width, y), (x+width, y+wall), (x, y+wall)],
            is_closed=True
        )
        h.paths.add_polyline_path(
            [(x, y+depth-wall), (x+width, y+depth-wall),
             (x+width, y+depth), (x, y+depth)],
            is_closed=True
        )
        h.paths.add_polyline_path(
            [(x, y+wall), (x+wall, y+wall),
             (x+wall, y+depth-wall), (x, y+depth-wall)],
            is_closed=True
        )
        h.paths.add_polyline_path(
            [(x+width-wall, y+wall), (x+width, y+wall),
             (x+width, y+depth-wall), (x+width-wall, y+depth-wall)],
            is_closed=True
        )
    except Exception:
        pass  # Hatching not critical if ezdxf version incompatible


def verify_section_alignment(frame_width, frame_height, section_spacing):
    """
    Verify orthographic section alignment parameters.
    
    Returns:
        dict with positioning and validation status
    """
    errors = []
    
    if frame_width <= 0:
        errors.append(f'frame_width must be positive, got {frame_width}')
    if frame_height <= 0:
        errors.append(f'frame_height must be positive, got {frame_height}')
    if section_spacing < 0:
        errors.append(f'section_spacing must be non-negative, got {section_spacing}')
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'elevation_x_range': (0, frame_width),
        'elevation_y_range': (0, frame_height),
        'section_x_position': frame_width + section_spacing,
        'section_y_aligned_at': 0
    }
