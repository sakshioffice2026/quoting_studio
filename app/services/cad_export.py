"""
Advanced fabrication-quality DXF drawing generator using ezdxf.
UPDATED: Parametric cill geometry, corrected orthographic sections,
specification-compliant layers, and true circular-window glass geometry.

Produces professional window fabrication drawings matching PWQ-3645 reference
standard:

  MODEL SPACE — three drawing views:
    1. ELEVATION  — front view with panes, mullions, opener symbols, dimensions
    2. SECTION    — horizontal cross-section through the frame showing profile,
                    glazing pocket, wall thickness
    3. SIDE VIEW  — vertical section through head and cill with glass unit
    4. SCHEDULE   — parts/glazing schedule table

  PAPER SPACE — ISO A4 sheet:
    - Title block (drawing number, material, scale, date, revision)
    - Viewport showing the elevation
    - Company / project metadata

Layers (SPECIFICATION COMPLIANT):
  FRAME_GEOMETRY     outer frame, mullions, glass          (white/7, 50pt)
  WINDOW_CILL        projecting sill/cill detail           (yellow/2, 50pt)
  SWING_LINES        opener indicator lines (dashed)       (blue/5, 25pt, dashed)
  DIMENSIONS         dimension callouts, measurements      (red/1, 18pt)
  BORDER_LAYOUT      sheet border, title block, grid       (white/7, 40pt)

PARAMETRIC FEATURES:
  - Cill_Horn_Length (mm): Left/right overhang extension
  - Cill_Nose_Depth (mm): Vertical projection below frame
  - Section_Spacing (mm): Gap between elevation and side view
  - Frame_Profile_Thickness (mm): Wall thickness

CURVED GLASS:
  - rectangular/rectangular windows keep the original rectangular glass
  - circular/round windows draw the frame as a circle
  - circular glass is clipped to the circular aperture, so a multi-pane
    circular window gets curved outer glass edges instead of rectangular panes
  - circular mullions/transoms are clipped to the circular aperture
"""

import io
import json
import logging
import math
from datetime import date


def _align(code):
    """Map legacy DXF group-72 horizontal justification codes."""
    from ezdxf.enums import TextEntityAlignment
    return {
        0: TextEntityAlignment.LEFT,
        1: TextEntityAlignment.CENTER,
        2: TextEntityAlignment.RIGHT,
    }[code]


logger = logging.getLogger(__name__)

# Default profile values (mm)
_DEFAULT_BAR = 40.0
_DEFAULT_WALL = 4.0
_DEFAULT_DEPTH = 52.0
_DEFAULT_REBATE = 20.0


# ================================================================
# PUBLIC ENTRY POINT
# ================================================================

def generate_window_dxf(window, panes, tenant_id: int = None, **params) -> bytes:
    """
    Generate an advanced fabrication DXF with parametric cill and sections.
    Returns UTF-8 encoded bytes.

    Args:
        window: Window ORM object (width_mm, height_mm, design_json, etc.)
        panes: List of pane ORM objects
        tenant_id: Tenant ID for profile lookup
        **params: Optional parameter overrides:
            - cill_horn_length (mm, default 40.0)
            - cill_nose_depth (mm, default 30.0)
            - section_spacing (mm, default 300.0)
            - frame_profile_thickness (mm, default 4.0)

    Returns:
        DXF file data as UTF-8 bytes
    """
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        logger.error("ezdxf not installed — DXF export unavailable")
        return b""

    try:
        profile = _get_profile(
            tenant_id,
            getattr(window, "material", "Aluminium"),
            window,
        )
        return _build(window, panes, profile, tenant_id, **params)
    except Exception as exc:
        logger.exception(
            "DXF generation failed window=%s: %s",
            getattr(window, "id", "?"),
            exc,
        )
        raise


# ================================================================
# PROFILE LOOKUP
# ================================================================

def _get_profile(tenant_id, material, window=None):
    """Load profile parameters. Priority:
       1. window.profile_system_id -> ProfileSystem
       2. tenant's is_default=True CadProfile for this material
       3. hardcoded fallback
    """
    prof = {
        "bar": _DEFAULT_BAR,
        "wall": _DEFAULT_WALL,
        "depth": _DEFAULT_DEPTH,
        "rebate": _DEFAULT_REBATE,
        "name": "PWQ-3645",
        "ref": "PWQ-3645",
    }

    if not tenant_id:
        return prof

    try:
        from app.models.cad_profile import CadProfile
        from app.models.profile_system import ProfileSystem

        p = None

        sys_id = getattr(window, "profile_system_id", None) if window else None
        if sys_id:
            psys = ProfileSystem.query.get(sys_id)
            if psys:
                slot_id = psys.head_id or psys.jamb_id or psys.cill_id
                if slot_id:
                    p = CadProfile.query.get(slot_id)

        if p is None:
            p = (
                CadProfile.query.filter_by(
                    tenant_id=tenant_id,
                    material=material,
                    is_active=True,
                    is_default=True,
                ).first()
                or CadProfile.query.filter_by(
                    tenant_id=tenant_id,
                    is_active=True,
                ).first()
            )

        if p:
            prof.update(
                bar=float(p.bar_width_mm),
                wall=float(p.wall_thickness_mm),
                depth=float(p.depth_mm),
                rebate=float(p.glass_rebate_mm),
                name=p.name,
                ref=p.drawing_ref or "CUSTOM",
            )
    except Exception as exc:
        logger.warning("Profile lookup failed: %s", exc)

    return prof


# ================================================================
# BUILDER
# ================================================================

def _build(window, panes, prof, tenant_id, **params) -> bytes:
    """Build the complete DXF document."""
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.units = 4

    _setup_layers(doc)
    _setup_dimstyle(doc, prof["bar"])
    _setup_text_styles(doc)

    msp = doc.modelspace()

    W = float(window.width_mm)
    H = float(window.height_mm)
    bar = prof["bar"]

    cill_horn = params.get("cill_horn_length", 40.0)
    cill_nose = params.get("cill_nose_depth", 30.0)
    sect_spacing = params.get("section_spacing", 300.0)
    frame_thick = params.get(
        "frame_profile_thickness",
        prof["wall"],
    )
    _ = frame_thick  # retained for API compatibility

    panes_data = _parse_panes(panes, W, H)
    has_cill = _get_cill_flag(window)
    shape = _get_window_shape(window)

    # ---- VIEW 1: ELEVATION (origin 0,0) ----
    _elevation(
        msp,
        W,
        H,
        bar,
        panes_data,
        shape=shape,
        window=window,
        panes=panes,
        tenant_id=tenant_id,
    )

    # ---- PARAMETRIC CILL (below elevation) ----
    if has_cill:
        _cill(msp, W, cill_horn, cill_nose)

    # ---- VIEW 2: HORIZONTAL SECTION A-A ----
    section_y = -(H * 0.45 + 300)
    _horizontal_section(msp, W, prof, section_y)

    # ---- VIEW 3: VERTICAL SECTION B-B ----
    sect_x = W + sect_spacing
    side_bottom_y = _vertical_section(
        msp,
        H,
        prof,
        sect_x,
        has_cill=has_cill,
    )

    # ---- VIEW 4: SCHEDULE TABLE ----
    _schedule(msp, W, H, panes_data, prof)

    # ---- DIMENSIONS ----
    bbox = _calculate_extents(
        W,
        H,
        sect_x,
        prof["depth"],
        cill_nose if has_cill else 0,
        prof["bar"],
    )
    _dimensions(
        msp,
        W,
        H,
        panes_data,
        section_y,
        sect_x,
        prof["depth"],
        bbox,
    )

    # ---- TITLE BLOCK ----
    _titleblock_ms(
        msp,
        W,
        H,
        bar,
        section_y,
        prof,
        window,
        tenant_id,
        side_bottom_y,
        bbox,
    )

    # ---- SHEET BORDER ----
    _sheet_border(msp, bbox, bar)

    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode("utf-8")

    logger.info(
        "Advanced DXF built: window=%s %dx%d shape=%s (cill=%s, "
        "sect_spacing=%.0f) → %d bytes",
        getattr(window, "id", "?"),
        int(W),
        int(H),
        shape,
        has_cill,
        sect_spacing,
        len(data),
    )
    return data


# ================================================================
# LAYERS
# ================================================================

def _setup_layers(doc):
    """Create and configure specification-compliant layers."""
    specs = [
        ("FRAME_GEOMETRY", 7, 50, "CONTINUOUS"),
        ("WINDOW_CILL", 2, 50, "CONTINUOUS"),
        ("SWING_LINES", 5, 25, "DASHED"),
        ("DIMENSIONS", 1, 18, "CONTINUOUS"),
        ("BORDER_LAYOUT", 7, 40, "CONTINUOUS"),
    ]

    for name, colour, lw, lt in specs:
        if name in doc.layers:
            layer = doc.layers.get(name)
        else:
            layer = doc.layers.new(name)
        layer.color = colour
        layer.lineweight = lw
        if lt in doc.linetypes:
            layer.dxf.linetype = lt


def _setup_text_styles(doc):
    """Configure text styles."""
    if "FABTITLE" not in doc.styles:
        try:
            doc.styles.new(
                "FABTITLE",
                dxfattribs={"font": "isocp.shx"},
            )
        except Exception:
            pass


def _setup_dimstyle(doc, bar):
    """Create dimension style scaled to frame bar width."""
    import ezdxf

    if "FAB" in doc.dimstyles:
        return

    try:
        ds = doc.dimstyles.new("FAB")
        ds.set_arrows(blk=ezdxf.ARROWS.architectural_tick)
        ds.dxf.dimtxt = bar * 0.34
        ds.dxf.dimasz = bar * 0.22
        ds.dxf.dimexo = bar * 0.14
        ds.dxf.dimexe = bar * 0.24
        ds.dxf.dimgap = bar * 0.10
        ds.dxf.dimdec = 0
        ds.dxf.dimclrt = 1
        ds.dxf.dimclre = 1
        ds.dxf.dimclrd = 1
        ds.dxf.dimtih = 0
    except Exception as exc:
        logger.warning("Dimstyle setup warning: %s", exc)


# ================================================================
# VIEW 1: ELEVATION
# ================================================================

def _elevation(msp, W, H, bar, panes_data, shape="rectangle",
                window=None, panes=None, tenant_id=None):
    """
    Draw front elevation.

    Rectangular windows use the original rectangular renderer.

    Circular windows are drawn strictly from the STEP solid (generated
    first via model3d.generate_3d, projected with headless FreeCAD) so
    this DXF can never disagree with the exported 3D/STEP model. Falls
    back to the parametric circle/arc renderer only if STEP generation
    is unavailable, or if window/panes weren't supplied by the caller.
    """
    shape = _normalise_shape(shape)

    if shape == "circular":
        if window is not None and panes is not None:
            try:
                _circular_elevation_from_step(
                    msp, window, panes, tenant_id, W, H,
                )
                return
            except Exception:
                logger.exception(
                    "STEP-derived circular elevation failed for window=%s "
                    "— falling back to parametric circle geometry",
                    getattr(window, "id", "?"),
                )
        _circular_elevation(
            msp,
            W,
            H,
            bar,
            panes_data,
        )
        return

    # Original rectangular elevation behaviour.
    msp.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 50,
        },
    )

    seen_x, seen_y = set(), set()

    for pane in panes_data:
        x_norm, y_norm, w_norm, h_norm, opening = pane

        rx = x_norm + w_norm
        if (
            0.001 < rx < 0.999
            and round(rx, 3) not in seen_x
        ):
            seen_x.add(round(rx, 3))
            mx = rx * W
            mb = bar * 0.6

            msp.add_lwpolyline(
                [
                    (mx - mb / 2, bar),
                    (mx + mb / 2, bar),
                    (mx + mb / 2, H - bar),
                    (mx - mb / 2, H - bar),
                ],
                close=True,
                dxfattribs={
                    "layer": "FRAME_GEOMETRY",
                    "lineweight": 35,
                },
            )

        ty = y_norm + h_norm
        if (
            0.001 < ty < 0.999
            and round(ty, 3) not in seen_y
        ):
            seen_y.add(round(ty, 3))
            my = ty * H
            mb = bar * 0.6

            msp.add_lwpolyline(
                [
                    (bar, my - mb / 2),
                    (W - bar, my - mb / 2),
                    (W - bar, my + mb / 2),
                    (bar, my + mb / 2),
                ],
                close=True,
                dxfattribs={
                    "layer": "FRAME_GEOMETRY",
                    "lineweight": 35,
                },
            )

        gx = x_norm * W + bar + 4
        gy = y_norm * H + bar + 4
        grx = (x_norm + w_norm) * W - bar - 4
        gry = (y_norm + h_norm) * H - bar - 4

        if grx > gx and gry > gy:
            msp.add_lwpolyline(
                [
                    (gx, gy),
                    (grx, gy),
                    (grx, gry),
                    (gx, gry),
                ],
                close=True,
                dxfattribs={"layer": "FRAME_GEOMETRY"},
            )

            if opening and opening != "Fixed":
                _opener_symbol(
                    msp,
                    gx,
                    gy,
                    grx - gx,
                    gry - gy,
                    opening,
                )


def _circular_elevation_from_step(msp, window, panes, tenant_id, W, H):
    """
    Circular-window elevation sourced strictly from the STEP solid: reuses
    (or triggers) the same STEP generation and FreeCAD front-view
    projection as the orthographic-views export, so the parametric DXF's
    circular frame/glass geometry is always identical to the STEP file.
    """
    import math
    from .orthographic_dxf import get_step_views

    views = get_step_views(window, panes, tenant_id=tenant_id)
    front = views.get("front") or {}
    frame_edges = front.get("frame") or front.get("visible") or []
    glass_by_label = front.get("glass") or {}
    if not frame_edges and not glass_by_label:
        raise RuntimeError("empty STEP front projection")

    all_pts = [p for e in frame_edges for p in e]
    for edges in glass_by_label.values():
        all_pts += [p for e in edges for p in e]
    x0 = min(p[0] for p in all_pts)
    y0 = min(p[1] for p in all_pts)

    for label, edges in glass_by_label.items():
        pts = [(px - x0, py - y0) for e in edges for px, py in e]
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        ordered = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        dedup = []
        for p in ordered:
            if not dedup or math.hypot(p[0] - dedup[-1][0], p[1] - dedup[-1][1]) > 0.5:
                dedup.append(p)
        if len(dedup) >= 3:
            msp.add_lwpolyline(
                dedup, close=True,
                dxfattribs={"layer": "FRAME_GEOMETRY", "lineweight": 18},
            )

    for edge in frame_edges:
        pts = [(px - x0, py - y0) for px, py in edge]
        if len(pts) >= 2:
            msp.add_lwpolyline(
                pts, dxfattribs={"layer": "FRAME_GEOMETRY", "lineweight": 50},
            )


def _circular_elevation(msp, W, H, bar, panes_data):
    """
    Draw a circular front elevation.

    The window's nominal width/height is treated as the outer diameter
    bounding box. The frame is represented by two concentric circles.

    Each pane is clipped against the inner circular aperture. For a 2x2
    pane grid, this produces four curved glass panels with arc-shaped outer
    edges instead of four rectangular glass boxes.
    """
    cx = W / 2.0
    cy = H / 2.0

    # True circle uses the smaller dimension as diameter. This avoids an
    # invalid ellipse when the stored width/height are slightly different.
    outer_r = min(W, H) / 2.0
    inner_r = max(0.0, outer_r - bar)

    # Outer and inner frame circles.
    msp.add_circle(
        (cx, cy),
        outer_r,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 50,
        },
    )

    if inner_r > 0:
        msp.add_circle(
            (cx, cy),
            inner_r,
            dxfattribs={
                "layer": "FRAME_GEOMETRY",
                "lineweight": 35,
            },
        )

    # Use the pane layout to create the actual glass panels.
    seen_vertical = set()
    seen_horizontal = set()

    for pane in panes_data:
        x_norm, y_norm, w_norm, h_norm, opening = pane

        # Pane bounds are in bottom-left normalized coordinates.
        x0 = x_norm * W + bar + 4
        y0 = y_norm * H + bar + 4
        x1 = (x_norm + w_norm) * W - bar - 4
        y1 = (y_norm + h_norm) * H - bar - 4

        if x1 <= x0 or y1 <= y0:
            continue

        # The pane is a rectangle only as a layout definition.
        # The actual glass is the intersection of that rectangle and
        # the circular aperture.
        glass_points = _circle_rectangle_intersection_polygon(
            cx,
            cy,
            inner_r - 2.0,
            x0,
            y0,
            x1,
            y1,
        )

        if len(glass_points) >= 3:
            msp.add_lwpolyline(
                glass_points,
                close=True,
                dxfattribs={
                    "layer": "FRAME_GEOMETRY",
                    "lineweight": 18,
                },
            )

        # Opening symbols stay inside the curved glass boundary.
        if opening and opening != "Fixed":
            _opener_symbol(
                msp,
                x0,
                y0,
                max(0.0, x1 - x0),
                max(0.0, y1 - y0),
                opening,
            )

        # Draw internal mullions/transoms only once. Their endpoints are
        # clipped to the circular aperture.
        right_x = x_norm + w_norm
        top_y = y_norm + h_norm

        if (
            0.001 < right_x < 0.999
            and round(right_x, 6) not in seen_vertical
        ):
            seen_vertical.add(round(right_x, 6))
            x = right_x * W
            seg = _vertical_circle_segment(
                cx,
                cy,
                inner_r,
                x,
            )
            if seg:
                _draw_thick_segment(
                    msp,
                    seg[0],
                    seg[1],
                    bar * 0.6,
                    "FRAME_GEOMETRY",
                    35,
                )

        if (
            0.001 < top_y < 0.999
            and round(top_y, 6) not in seen_horizontal
        ):
            seen_horizontal.add(round(top_y, 6))
            y = top_y * H
            seg = _horizontal_circle_segment(
                cx,
                cy,
                inner_r,
                y,
            )
            if seg:
                _draw_thick_segment(
                    msp,
                    seg[0],
                    seg[1],
                    bar * 0.6,
                    "FRAME_GEOMETRY",
                    35,
                )


def _circle_rectangle_intersection_polygon(
    cx,
    cy,
    radius,
    x0,
    y0,
    x1,
    y1,
    samples_per_arc=20,
):
    """
    Return a polygon approximating:
        rectangle(x0,y0,x1,y1) ∩ circle(cx,cy,radius)

    The rectangle is only the pane layout. The resulting polygon follows
    the circle wherever the circular aperture cuts the pane.

    This deliberately uses a dense polyline rather than a rectangle so
    AutoCAD/LibreCAD will visibly show the curved glass boundary.
    """
    if radius <= 0:
        return []

    x0, x1 = sorted((float(x0), float(x1)))
    y0, y1 = sorted((float(y0), float(y1)))

    candidates = []

    def add_point(x, y):
        if (
            x0 - 1e-7 <= x <= x1 + 1e-7
            and y0 - 1e-7 <= y <= y1 + 1e-7
        ):
            candidates.append((float(x), float(y)))

    # Rectangle corners inside circle.
    for px, py in (
        (x0, y0),
        (x1, y0),
        (x1, y1),
        (x0, y1),
    ):
        if (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2 + 1e-7:
            add_point(px, py)

    # Circle/vertical-edge intersections.
    for x in (x0, x1):
        dx = x - cx
        disc = radius ** 2 - dx ** 2
        if disc >= -1e-9:
            root = math.sqrt(max(0.0, disc))
            add_point(x, cy - root)
            add_point(x, cy + root)

    # Circle/horizontal-edge intersections.
    for y in (y0, y1):
        dy = y - cy
        disc = radius ** 2 - dy ** 2
        if disc >= -1e-9:
            root = math.sqrt(max(0.0, disc))
            add_point(cx - root, y)
            add_point(cx + root, y)

    # Add points on the circle that lie within the rectangle.
    # The angular sweep creates the curved boundary.
    for i in range(samples_per_arc * 4):
        theta = 2.0 * math.pi * i / (samples_per_arc * 4)
        px = cx + radius * math.cos(theta)
        py = cy + radius * math.sin(theta)
        if (
            x0 - 1e-7 <= px <= x1 + 1e-7
            and y0 - 1e-7 <= py <= y1 + 1e-7
        ):
            add_point(px, py)

    # De-duplicate.
    unique = {}
    for px, py in candidates:
        key = (round(px, 6), round(py, 6))
        unique[key] = (px, py)

    points = list(unique.values())
    if len(points) < 3:
        return []

    # Sort around centroid.
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)

    points.sort(
        key=lambda p: math.atan2(
            p[1] - my,
            p[0] - mx,
        )
    )

    return points


def _vertical_circle_segment(cx, cy, radius, x):
    """Return the line segment where x=constant intersects the circle."""
    dx = x - cx
    disc = radius ** 2 - dx ** 2

    if disc < -1e-7:
        return None

    root = math.sqrt(max(0.0, disc))
    return (
        (x, cy - root),
        (x, cy + root),
    )


def _horizontal_circle_segment(cx, cy, radius, y):
    """Return the line segment where y=constant intersects the circle."""
    dy = y - cy
    disc = radius ** 2 - dy ** 2

    if disc < -1e-7:
        return None

    root = math.sqrt(max(0.0, disc))
    return (
        (cx - root, y),
        (cx + root, y),
    )


def _draw_thick_segment(
    msp,
    p1,
    p2,
    thickness,
    layer,
    lineweight,
):
    """Draw a narrow rectangular mullion around a clipped line segment."""
    x1, y1 = p1
    x2, y2 = p2

    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)

    if length <= 1e-9:
        return

    nx = -dy / length * thickness / 2.0
    ny = dx / length * thickness / 2.0

    points = [
        (x1 + nx, y1 + ny),
        (x2 + nx, y2 + ny),
        (x2 - nx, y2 - ny),
        (x1 - nx, y1 - ny),
    ]

    msp.add_lwpolyline(
        points,
        close=True,
        dxfattribs={
            "layer": layer,
            "lineweight": lineweight,
        },
    )


def _opener_symbol(msp, x, y, w, h, opening):
    """Draw dashed swing/opening indicators."""
    d = {
        "layer": "SWING_LINES",
        "linetype": "DASHED",
        "lineweight": 25,
    }

    cx, cy = x + w / 2, y + h / 2

    if "Left" in opening or opening == "Casement":
        msp.add_line(
            (x + w, y),
            (x + w * 0.1, cy),
            dxfattribs=d,
        )
        msp.add_line(
            (x + w, y + h),
            (x + w * 0.1, cy),
            dxfattribs=d,
        )
    elif "Right" in opening:
        msp.add_line(
            (x, y),
            (x + w * 0.9, cy),
            dxfattribs=d,
        )
        msp.add_line(
            (x, y + h),
            (x + w * 0.9, cy),
            dxfattribs=d,
        )
    elif "Top" in opening:
        msp.add_line(
            (x, y),
            (cx, y + h * 0.9),
            dxfattribs=d,
        )
        msp.add_line(
            (x + w, y),
            (cx, y + h * 0.9),
            dxfattribs=d,
        )
    elif "Slid" in opening:
        msp.add_line(
            (x + w * 0.15, cy),
            (x + w * 0.85, cy),
            dxfattribs=d,
        )


# ================================================================
# PARAMETRIC CILL
# ================================================================

def _cill(msp, W, horn_length=40.0, nose_depth=30.0):
    """Draw parametric projecting cill board below the frame."""
    cill_x0 = -horn_length
    cill_x1 = W + horn_length
    cill_y0 = -nose_depth
    cill_y1 = 0.0

    pts_main = [
        (cill_x0, cill_y0),
        (cill_x1, cill_y0),
        (cill_x1, cill_y1),
        (cill_x0, cill_y1),
    ]

    msp.add_lwpolyline(
        pts_main,
        close=True,
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 50,
        },
    )

    drip_y = cill_y0 + nose_depth * 0.35
    msp.add_line(
        (cill_x0, drip_y),
        (cill_x1, drip_y),
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 25,
        },
    )

    for ex in (cill_x0, cill_x1):
        msp.add_line(
            (ex, cill_y0),
            (ex, cill_y1),
            dxfattribs={
                "layer": "WINDOW_CILL",
                "lineweight": 50,
            },
        )

    msp.add_line(
        (cill_x0, cill_y1),
        (cill_x1, cill_y1),
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 40,
        },
    )

    stiffener_inset = horn_length * 0.2
    for stiff_x in (
        cill_x0 + stiffener_inset,
        cill_x1 - stiffener_inset,
    ):
        if cill_x0 < stiff_x < cill_x1:
            msp.add_line(
                (stiff_x, cill_y0),
                (stiff_x, drip_y),
                dxfattribs={
                    "layer": "WINDOW_CILL",
                    "lineweight": 15,
                },
            )

    label_x = W / 2
    label_y = cill_y0 - nose_depth * 0.15

    msp.add_text(
        "CILL",
        dxfattribs={
            "layer": "WINDOW_CILL",
            "height": 30,
        },
    ).set_placement(
        (label_x, label_y),
        align=_align(1),
    )

    msp.add_text(
        f"{horn_length:.0f}mm horn × {nose_depth:.0f}mm depth",
        dxfattribs={
            "layer": "WINDOW_CILL",
            "height": 18,
        },
    ).set_placement(
        (label_x, label_y - nose_depth * 0.2),
        align=_align(1),
    )


# ================================================================
# VIEW 2: HORIZONTAL SECTION A-A
# ================================================================

def _horizontal_section(msp, W, prof, section_y):
    """Draw horizontal cross-section (plan strip) through frame jambs."""
    bar = prof["bar"]
    wall = prof["wall"]
    depth = prof["depth"]

    section_h = depth + 40
    section_bot = section_y - section_h

    _profile_box_h(
        msp,
        0,
        section_bot,
        bar,
        depth,
        wall,
        section_y,
    )

    _profile_box_h(
        msp,
        W - bar,
        section_bot,
        bar,
        depth,
        wall,
        section_y,
        mirror=True,
    )

    msp.add_line(
        (bar, section_y),
        (W - bar, section_y),
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 20,
        },
    )

    msp.add_line(
        (bar, section_bot),
        (W - bar, section_bot),
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 20,
        },
    )

    glass_x1 = bar - prof["rebate"] * 0.4
    glass_x2 = W - bar + prof["rebate"] * 0.4
    gc_y = section_bot + depth / 2
    pane_gap = depth * 0.18

    for gy in (
        gc_y - pane_gap / 2,
        gc_y + pane_gap / 2,
    ):
        msp.add_line(
            (glass_x1, gy),
            (glass_x2, gy),
            dxfattribs={
                "layer": "FRAME_GEOMETRY",
                "lineweight": 18,
            },
        )

    msp.add_text(
        "HORIZONTAL SECTION A-A",
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": bar * 0.5,
        },
    ).set_placement(
        (W / 2, section_bot - bar * 1.4),
        align=_align(1),
    )

    msp.add_text(
        f'PROFILE: {prof["ref"]} | {bar:.0f}mm FRAME | '
        f'{wall:.0f}mm WALL | {depth:.0f}mm DEPTH',
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": bar * 0.34,
        },
    ).set_placement(
        (W / 2, section_bot - bar * 2.2),
        align=_align(1),
    )


def _profile_box_h(
    msp,
    x,
    y_bot,
    w,
    depth,
    wall,
    y_top,
    mirror=False,
):
    """Draw a hollow profile box for horizontal section."""
    _ = mirror

    msp.add_lwpolyline(
        [
            (x, y_bot),
            (x + w, y_bot),
            (x + w, y_top),
            (x, y_top),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 25,
        },
    )

    msp.add_lwpolyline(
        [
            (x + wall, y_bot + wall),
            (x + w - wall, y_bot + wall),
            (x + w - wall, y_top - wall),
            (x + wall, y_top - wall),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 15,
        },
    )


# ================================================================
# VIEW 3: VERTICAL SECTION B-B
# ================================================================

def _vertical_section(
    msp,
    H,
    prof,
    sect_x,
    has_cill=False,
):
    """
    Draw vertical cross-section through HEAD and CILL/SILL.

    Returns:
        Lowest Y reached by section geometry.
    """
    bar = prof["bar"]
    wall = prof["wall"]
    depth = prof["depth"]
    rebate = prof["rebate"]
    scale = 3.0

    bar_s = bar * scale
    wall_s = wall * scale
    depth_s = depth * scale
    reb_s = rebate * scale

    ty0 = H - bar_s
    ty1 = H

    _profile_box_v(
        msp,
        sect_x,
        ty0,
        depth_s,
        bar_s,
        wall_s,
        mirror=True,
    )

    gap = bar_s * 2.0

    by1 = gap
    by0 = by1 - bar_s

    if has_cill:
        by0_nominal = by0
        lip_s = 40.0 * scale
        cill_top = _cill_section_profile(
            msp,
            sect_x,
            by0_nominal,
            depth_s,
            bar_s,
            wall_s,
            lip_s,
        )
        by1 = cill_top
        section_bottom = by0_nominal - bar_s * 0.5
    else:
        _profile_box_v(
            msp,
            sect_x,
            by0,
            depth_s,
            bar_s,
            wall_s,
            mirror=False,
        )
        section_bottom = by0 - bar_s * 0.3

    gc_x = sect_x + depth_s / 2
    gy1 = by1 + reb_s * 0.4
    gy2 = ty0 - reb_s * 0.4
    pane_gap = depth_s * 0.18

    for gx in (
        gc_x - pane_gap / 2,
        gc_x + pane_gap / 2,
    ):
        msp.add_line(
            (gx, gy1),
            (gx, gy2),
            dxfattribs={
                "layer": "FRAME_GEOMETRY",
                "lineweight": 18,
            },
        )

    msp.add_lwpolyline(
        [
            (gc_x - pane_gap / 2, gy1),
            (gc_x - pane_gap / 2, gy1 + depth_s * 0.05),
            (gc_x + pane_gap / 2, gy1 + depth_s * 0.05),
            (gc_x + pane_gap / 2, gy1),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 18,
        },
    )

    msp.add_lwpolyline(
        [
            (gc_x - pane_gap / 2, gy2),
            (gc_x - pane_gap / 2, gy2 - depth_s * 0.05),
            (gc_x + pane_gap / 2, gy2 - depth_s * 0.05),
            (gc_x + pane_gap / 2, gy2),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 18,
        },
    )

    label_x = sect_x + depth_s / 2

    msp.add_text(
        "VERTICAL SECTION B-B",
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": bar * 0.55,
        },
    ).set_placement(
        (label_x, section_bottom - bar * 1.4),
        align=_align(1),
    )

    msp.add_text(
        f'PROFILE: {prof["ref"]} | {bar:.0f}mm FRAME | '
        f'{wall:.0f}mm WALL | {depth:.0f}mm DEPTH',
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": bar * 0.34,
        },
    ).set_placement(
        (label_x, section_bottom - bar * 2.2),
        align=_align(1),
    )

    return section_bottom


def _profile_box_v(
    msp,
    x,
    y,
    width,
    height,
    wall,
    mirror=False,
):
    """Draw a hollow profile box for vertical section."""
    _ = mirror

    msp.add_lwpolyline(
        [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 35,
        },
    )

    msp.add_lwpolyline(
        [
            (x + wall, y + wall),
            (x + width - wall, y + wall),
            (x + width - wall, y + height - wall),
            (x + wall, y + height - wall),
        ],
        close=True,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "lineweight": 18,
        },
    )


def _cill_section_profile(
    msp,
    x0,
    y0,
    depth_s,
    bar_s,
    wall_s,
    lip_s,
):
    """Draw cill cross-section in vertical view."""
    _ = wall_s

    cill_h = bar_s * 0.55
    ox0 = x0 - lip_s
    ox1 = x0 + depth_s
    oy0 = y0
    oy1 = y0 + cill_h
    upstand = cill_h * 0.35

    pts = [
        (ox0, oy0),
        (ox1, oy0),
        (ox1, oy1 + upstand),
        (ox0, oy1),
    ]

    msp.add_lwpolyline(
        pts,
        close=True,
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 35,
        },
    )

    drip_y = oy0 + cill_h * 0.3
    msp.add_line(
        (ox0, drip_y),
        (ox1, drip_y),
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 18,
        },
    )

    msp.add_line(
        (ox0, oy1),
        (ox1, oy1),
        dxfattribs={
            "layer": "WINDOW_CILL",
            "lineweight": 25,
        },
    )

    return oy1


# ================================================================
# VIEW 4: SCHEDULE TABLE
# ================================================================

def _schedule(msp, W, H, panes_data, prof):
    """Draw pane schedule table to the right of elevation."""
    bar = prof["bar"]
    tx = W + bar * 5
    ty = H
    rh = bar * 0.8
    th = bar * 0.34
    col_w = [
        bar * 1.2,
        bar * 3.5,
        bar * 3.5,
        bar * 2.2,
    ]
    total_w = sum(col_w)
    n = len(panes_data) + 1

    msp.add_lwpolyline(
        [
            (tx, ty),
            (tx + total_w, ty),
            (tx + total_w, ty - n * rh),
            (tx, ty - n * rh),
        ],
        close=True,
        dxfattribs={
            "layer": "BORDER_LAYOUT",
            "lineweight": 35,
        },
    )

    msp.add_line(
        (tx, ty - rh),
        (tx + total_w, ty - rh),
        dxfattribs={
            "layer": "BORDER_LAYOUT",
            "lineweight": 20,
        },
    )

    cx = tx
    headers = ["#", "Opener", "Glazing", "Size"]

    for i, hdr in enumerate(headers):
        if i > 0:
            msp.add_line(
                (cx, ty - n * rh),
                (cx, ty),
                dxfattribs={
                    "layer": "BORDER_LAYOUT",
                    "lineweight": 15,
                },
            )

        msp.add_text(
            hdr,
            dxfattribs={
                "layer": "FRAME_GEOMETRY",
                "height": th,
            },
        ).set_placement(
            (cx + col_w[i] * 0.5, ty - rh * 0.45),
            align=_align(1),
        )

        cx += col_w[i]

    for r_idx, pane in enumerate(panes_data):
        x_norm, y_norm, w_norm, h_norm, opening = pane
        _ = x_norm, y_norm

        ry = ty - (r_idx + 2) * rh

        msp.add_line(
            (tx, ry),
            (tx + total_w, ry),
            dxfattribs={
                "layer": "BORDER_LAYOUT",
                "lineweight": 10,
            },
        )

        w_mm = int(round(w_norm * W))
        h_mm = int(round(h_norm * H))
        vals = [
            str(r_idx + 1),
            opening or "Fixed",
            "DGU",
            f"{w_mm}×{h_mm}",
        ]

        cx = tx
        for i, val in enumerate(vals):
            msp.add_text(
                val,
                dxfattribs={
                    "layer": "FRAME_GEOMETRY",
                    "height": th * 0.9,
                },
            ).set_placement(
                (cx + col_w[i] * 0.5, ry + rh * 0.35),
                align=_align(1),
            )
            cx += col_w[i]


# ================================================================
# DIMENSIONS & BOUNDING BOX
# ================================================================

def _calculate_extents(
    W,
    H,
    sect_x,
    depth,
    cill_nose,
    bar=40.0,
):
    """Auto-calculate geometry bounding box."""
    x_min = -bar * 4
    x_max = sect_x + depth * 3 + bar * 5
    y_min = -cill_nose - bar * 5
    y_max = H + bar * 4

    return {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
    }


def _dimensions(
    msp,
    W,
    H,
    panes_data,
    section_y,
    sect_x,
    depth,
    bbox,
):
    """Draw overall and pane dimensions."""
    _ = panes_data, section_y, bbox

    layer_dim = "DIMENSIONS"

    msp.add_line(
        (-50, H + 120),
        (W + 50, H + 120),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_line(
        (-50, H + 100),
        (-50, H + 120),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_line(
        (W + 50, H + 100),
        (W + 50, H + 120),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_text(
        f"{W:.0f}",
        dxfattribs={
            "layer": layer_dim,
            "height": 30,
        },
    ).set_placement(
        (W / 2, H + 140),
        align=_align(1),
    )

    msp.add_line(
        (sect_x + depth * 3.5, 0),
        (sect_x + depth * 3.5, H),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_line(
        (sect_x + depth * 3.3, 0),
        (sect_x + depth * 3.5, 0),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_line(
        (sect_x + depth * 3.3, H),
        (sect_x + depth * 3.5, H),
        dxfattribs={
            "layer": layer_dim,
            "lineweight": 15,
        },
    )

    msp.add_text(
        f"{H:.0f}",
        dxfattribs={
            "layer": layer_dim,
            "height": 30,
        },
    ).set_placement(
        (sect_x + depth * 3.8, H / 2),
        align=_align(1),
    )


def _sheet_border(msp, bbox, bar):
    """Draw sheet border around all content."""
    margin = bar * 4

    x0 = bbox["x_min"] - margin
    x1 = bbox["x_max"] + margin
    y0 = bbox["y_min"] - margin
    y1 = bbox["y_max"] + margin

    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={
            "layer": "BORDER_LAYOUT",
            "lineweight": 50,
        },
    )

    m2 = bar * 0.8
    msp.add_lwpolyline(
        [
            (x0 + m2, y0 + m2),
            (x1 - m2, y0 + m2),
            (x1 - m2, y1 - m2),
            (x0 + m2, y1 - m2),
        ],
        close=True,
        dxfattribs={
            "layer": "BORDER_LAYOUT",
            "lineweight": 20,
        },
    )


# ================================================================
# TITLE BLOCK
# ================================================================

def _fit_text_height(
    text,
    avail_w,
    max_h,
    char_w_ratio=0.6,
):
    """Fit text within an available cell width."""
    if not text:
        return max_h

    est_w_per_h = max(len(text), 1) * char_w_ratio
    return min(
        max_h,
        avail_w / est_w_per_h,
    )


def _titleblock_ms(
    msp,
    W,
    H,
    bar,
    section_y,
    prof,
    window,
    tenant_id,
    side_bottom_y=None,
    bbox=None,
):
    """
    Draw title block with drawing info — three bordered cells.
    """
    _ = tenant_id

    if bbox is None:
        bbox = {
            "x_min": -bar * 4,
            "x_max": W + bar * 15,
            "y_min": section_y - bar * 5,
            "y_max": H + bar * 4,
        }

    tb_h = bar * 8
    tb_y1 = min(
        section_y,
        side_bottom_y if side_bottom_y else section_y,
    ) - bar * 3
    tb_y0 = tb_y1 - tb_h

    bx0 = bbox["x_min"] - bar * 2
    bx1 = bbox["x_max"] + bar * 2
    bw = bx1 - bx0

    cell1_x1 = bx0 + bw * 0.28
    cell2_x1 = bx0 + bw * 0.68
    margin = bw * 0.015

    msp.add_lwpolyline(
        [(bx0, tb_y0), (bx1, tb_y0), (bx1, tb_y1), (bx0, tb_y1)],
        close=True,
        dxfattribs={
            "layer": "BORDER_LAYOUT",
            "lineweight": 40,
        },
    )

    for vx in (cell1_x1, cell2_x1):
        msp.add_line(
            (vx, tb_y0),
            (vx, tb_y1),
            dxfattribs={
                "layer": "BORDER_LAYOUT",
                "lineweight": 25,
            },
        )

    company = "QUOTING STUDIO"
    try:
        if hasattr(window, "project") and window.project:
            company = (
                window.project.tenant.name or company
            ).upper()
    except Exception:
        pass

    company_avail_w = cell1_x1 - bx0 - margin * 2
    company_h = _fit_text_height(
        company,
        company_avail_w,
        tb_h * 0.18,
    )

    msp.add_text(
        company,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": company_h,
        },
    ).set_placement(
        (bx0 + margin, tb_y0 + tb_h * 0.5),
        align=_align(0),
    )

    w_mm = int(window.width_mm)
    h_mm = int(window.height_mm)
    mat = getattr(window, "material", "Aluminium")
    colour = getattr(window, "frame_colour_name", "")

    info_text = f"{w_mm}×{h_mm}mm | {mat}"
    if colour:
        info_text += f" {colour}"

    info_avail_w = cell2_x1 - cell1_x1 - margin * 2
    info_h = _fit_text_height(
        info_text,
        info_avail_w,
        tb_h * 0.14,
    )

    msp.add_text(
        info_text,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": info_h,
        },
    ).set_placement(
        (cell1_x1 + margin, tb_y0 + tb_h * 0.5),
        align=_align(0),
    )

    drw_no = f'QS-{getattr(window, "id", "?")}'
    date_str = date.today().strftime("%d/%m/%Y")
    right_avail_w = bx1 - cell2_x1 - margin * 2

    drw_no_text = f"Drw: {drw_no}"
    date_text = f"Date: {date_str}"

    drw_h = _fit_text_height(
        drw_no_text,
        right_avail_w,
        tb_h * 0.12,
    )
    date_h = _fit_text_height(
        date_text,
        right_avail_w,
        tb_h * 0.12,
    )

    msp.add_text(
        drw_no_text,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": drw_h,
        },
    ).set_placement(
        (bx1 - margin, tb_y0 + tb_h * 0.65),
        align=_align(2),
    )

    msp.add_text(
        date_text,
        dxfattribs={
            "layer": "FRAME_GEOMETRY",
            "height": date_h,
        },
    ).set_placement(
        (bx1 - margin, tb_y0 + tb_h * 0.25),
        align=_align(2),
    )


# ================================================================
# HELPERS
# ================================================================

def _normalise_shape(value):
    """Normalise all known round/circular labels."""
    if value is None:
        return "rectangle"

    value = str(value).strip().lower()

    aliases = {
        "rectangular": "rectangle",
        "rect": "rectangle",
        "square": "rectangle",
        "round": "circular",
        "circle": "circular",
        "circular": "circular",
        "arched": "arched",
        "arch": "arched",
        "gothic": "gothic",
    }

    return aliases.get(value, value or "rectangle")


def _get_window_shape(window):
    """
    Read the selected shape from design_json first, then window.shape.

    Supports:
      design_json = {"shape": "circular"}
      design_json = {"frame": {"shape": "circular"}}
      window.shape = "circular"
      window.shape = "round"
    """
    raw = getattr(window, "design_json", None)

    if isinstance(raw, dict):
        design = raw
    else:
        design = {}
        if raw:
            try:
                design = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning(
                    "Could not parse design_json while resolving shape"
                )

    candidates = [
        design.get("shape"),
        design.get("windowShape"),
        (design.get("frame") or {}).get("shape"),
        getattr(window, "shape", None),
    ]

    for candidate in candidates:
        if candidate:
            return _normalise_shape(candidate)

    return "rectangle"


def _get_cill_flag(window):
    """Extract cill.enabled from design_json."""
    try:
        raw = getattr(window, "design_json", None)

        if isinstance(raw, dict):
            design = raw
        elif raw:
            design = json.loads(raw)
        else:
            design = {}

        frame_cfg = design.get("frame", {}) or {}

        return bool(
            frame_cfg.get("cill", False)
            or (
                isinstance(frame_cfg.get("cill"), dict)
                and frame_cfg["cill"].get("enabled", False)
            )
        )
    except Exception as exc:
        logger.warning(
            "Could not parse design_json: %s",
            exc,
        )

    return False


def _parse_panes(panes, W, H):
    """Extract pane geometry from ORM objects."""
    _ = W, H

    panes_data = []

    for p in panes or []:
        x_norm = float(
            getattr(p, "x_norm", 0.0)
        )
        y_norm = float(
            getattr(p, "y_norm", 0.0)
        )
        w_norm = float(
            getattr(p, "w_norm", 1.0)
        )
        h_norm = float(
            getattr(p, "h_norm", 1.0)
        )
        opener = str(
            getattr(p, "opener_type", "Fixed")
            or "Fixed"
        )

        panes_data.append(
            (
                x_norm,
                y_norm,
                w_norm,
                h_norm,
                opener,
            )
        )

    return (
        panes_data
        if panes_data
        else [(0.0, 0.0, 1.0, 1.0, "Fixed")]
    )