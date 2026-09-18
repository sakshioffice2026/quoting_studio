"""
Door threshold / sill cross-section geometry — hardcoded, standalone test only.

NOT wired into frame_assembly.py / model3d.py / model3d_freecad.py yet.
This module exists so door_threshold_extrude_test.py (repo root) can
export a STEP (3D) and a DXF (2D engineering) check independent of the
main window/door pipeline.

Profile source (software fact): points below are copied verbatim from
import_data/Sections/lower base of door frame.dxf (single closed
LWPOLYLINE, 53 vertices). Bounding box = 165.0 x 60.0 mm, which matches
the circled dimensions (165, 60, 55) in the reference drawing crop
supplied earlier. This is the real traced section, not a placeholder.

Units: mm. Local axes: X = bar (across profile), Y = depth
(through-wall) — i.e. plain 2D (x, y) as digitised, unrelated to the
window-pipeline's (u, v)->(Y, Z) convention used in model3d_freecad.py.
"""

PROFILE_NAME = "DoorThreshold_LowerBase"

# Verbatim (x, y) vertices traced from the source DXF, in order, closed.
THRESHOLD_PROFILE_POINTS = [
    (37.73, 15.67),
    (105.73, 15.67),
    (106.73, 16.67),
    (106.73, 22.17),
    (107.23, 22.67),
    (118.23, 22.67),
    (118.73, 22.17),
    (118.73, 16.87),
    (119.73, 15.87),
    (130.73, 15.87),
    (131.73, 16.87),
    (131.73, 22.17),
    (132.23, 22.67),
    (143.23, 22.67),
    (143.73, 22.17),
    (143.73, 16.87),
    (144.73, 15.87),
    (155.73, 15.87),
    (156.73, 16.87),
    (156.73, 22.17),
    (157.23, 22.67),
    (168.23, 22.67),
    (168.73, 22.17),
    (168.73, 16.67),
    (169.73, 15.67),
    (179.73, 15.67),
    (182.73, 18.67),
    (182.73, 64.67),
    (181.73, 65.67),
    (181.02, 65.67),
    (180.72, 65.96),
    (174.93, 73.6),
    (174.73, 73.89),
    (174.72, 74.68),
    (173.72, 75.67),
    (157.82, 75.67),
    (156.82, 74.68),
    (156.74, 64.66),
    (156.43, 63.95),
    (156.43, 56.67),
    (152.43, 56.67),
    (152.43, 63.47),
    (152.27, 63.47),
    (152.21, 63.47),
    (131.65, 60.94),
    (130.77, 59.96),
    (130.74, 56.35),
    (129.86, 55.36),
    (23.0, 42.24),
    (17.73, 36.29),
    (17.73, 17.67),
    (19.73, 15.67),
    (25.73, 15.67),
]


def get_bbox():
    xs = [p[0] for p in THRESHOLD_PROFILE_POINTS]
    ys = [p[1] for p in THRESHOLD_PROFILE_POINTS]
    return min(xs), min(ys), max(xs), max(ys)


def get_profile_points_normalised():
    """Profile shifted so its bounding box starts at (0, 0)."""
    minx, miny, _, _ = get_bbox()
    return [(round(x - minx, 3), round(y - miny, 3)) for (x, y) in THRESHOLD_PROFILE_POINTS]


def draw_threshold_section(msp, origin=(0.0, 0.0), layer="WINDOW_CILL"):
    """
    Draw the threshold cross-section as a closed LWPOLYLINE on `layer`,
    plus overall width/height dimensions using the same
    msp.add_aligned_dim(...).render() pattern as engineering_dxf.py, so
    output matches this repo's existing engineering-DXF conventions.

    msp: ezdxf modelspace
    origin: (x, y) offset to draw at
    layer: target layer name (must already exist — call
           dxf_layers.setup_layers(doc) first)
    """
    ox, oy = origin
    pts = get_profile_points_normalised()
    poly_pts = [(x + ox, y + oy) for (x, y) in pts]

    msp.add_lwpolyline(
        poly_pts,
        close=True,
        dxfattribs={"layer": layer, "lineweight": 50},
    )

    _, _, maxx, maxy = get_bbox()
    W = maxx - get_bbox()[0]
    H = maxy - get_bbox()[1]

    dim_attribs = {"layer": "DIMENSIONS"}
    dim_override = {
        "dimtxt": 4.5, "dimasz": 3.2, "dimexe": 1.8, "dimexo": 1.2,
        "dimdec": 1, "dimclrt": 1, "dimclrd": 1, "dimclre": 1,
    }

    # Overall width
    dim = msp.add_aligned_dim(
        p1=(ox, oy - 10), p2=(ox + W, oy - 10),
        distance=0, dxfattribs=dim_attribs, override=dim_override,
    )
    dim.render()

    # Overall height
    dim = msp.add_aligned_dim(
        p1=(ox - 10, oy), p2=(ox - 10, oy + H),
        distance=0, dxfattribs=dim_attribs, override=dim_override,
    )
    dim.render()

    return poly_pts


def get_rings_for_pipeline():
    """
    Return the threshold profile in the coordinate convention expected by
    model3d._section_rings / model3d_freecad._mk_face for a HORIZONTAL member
    (plane='H'):

        u  = across the bar  → maps to world Y  (visible height from front)
        v  = through-wall    → maps to world Z  (wall depth)

    The DXF was traced with X = through-wall (165 mm) and Y = across (60 mm),
    which is the opposite of the pipeline convention.  This function swaps the
    axes so the solid renders correctly in the assembly:

        u = profile_Y  (0 .. 60 mm)   → bar   = 60.0 mm
        v = profile_X  (0 .. 165 mm)  → depth = 165.0 mm

    Returns
    -------
    dict with keys:
        "rings" : list-of-rings in pipeline (u, v) form — outer boundary only.
        "bar"   : 60.0  (mm across member, for _mk_face b2 = bar/2 centering)
        "depth" : 165.0 (mm through wall, for extrude length along Z)

    Usage in pipeline (model3d.py prepare_sections or wherever the member is
    built before being passed to model3d_freecad):

        from app.services.threshold_geometry import get_rings_for_pipeline
        p = get_rings_for_pipeline()
        m._rings   = p["rings"]
        m._sec_bar = p["bar"]
        m._sec_dep = p["depth"]
        m._has_dxf = True
    """
    pts_norm = get_profile_points_normalised()          # (x=0..165, y=0..60)
    ring_uv  = [(round(y, 3), round(x, 3)) for x, y in pts_norm]  # swap axes
    return {
        "rings": [ring_uv],
        "bar":   60.0,
        "depth": 165.0,
    }