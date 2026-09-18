"""
Head (top horizontal) member geometry — real traced profile, standalone test only.

NOT wired into frame_assembly.py / model3d.py / model3d_freecad.py.

Profile source: app/cad_sections/cad_sections/head.dxf
               (same geometry as import_data/Sections/upper base of frame.dxf)
Single closed LWPOLYLINE, 19 raw vertices — 1 duplicate vertex removed
(original index 13 == index 14, both (102.100, 47.469)), leaving 18 unique.
Bounding box: 90.0 x 35.0 mm.

Units: mm.  Local axes: X = width across profile, Y = depth (through-wall).
"""

PROFILE_NAME = "Head_UpperBaseOfFrame"

# Verbatim (x, y) vertices from head.dxf, in order, closed.
# Duplicate vertex at original index 14 removed.
HEAD_PROFILE_POINTS = [
    (14.100, 19.469),
    (50.350, 19.469),
    (51.100, 19.469),
    (51.100, 14.469),
    (63.100, 14.469),
    (63.100, 19.469),
    (75.350, 19.469),
    (76.100, 19.469),
    (76.100, 14.469),
    (88.100, 14.469),
    (88.100, 19.469),
    (100.100, 19.469),
    (102.100, 21.469),
    (102.100, 47.469),
    (100.100, 49.469),
    (14.100, 49.469),
    (12.100, 47.469),
    (12.100, 21.469),
]


def get_bbox():
    xs = [p[0] for p in HEAD_PROFILE_POINTS]
    ys = [p[1] for p in HEAD_PROFILE_POINTS]
    return min(xs), min(ys), max(xs), max(ys)


def get_head_bbox():
    return get_bbox()


def get_profile_points_normalised():
    """Profile shifted so its bounding box starts at (0, 0)."""
    minx, miny, _, _ = get_bbox()
    return [(round(x - minx, 3), round(y - miny, 3)) for (x, y) in HEAD_PROFILE_POINTS]


def draw_head_section(msp, origin=(0.0, 0.0), layer="WINDOW_CILL"):
    """
    Draw the head cross-section as a closed LWPOLYLINE on `layer`,
    plus overall width/height dimensions using the same
    msp.add_aligned_dim(...).render() pattern as engineering_dxf.py.

    msp    : ezdxf modelspace
    origin : (x, y) offset — pass (0, H_mm) to position at top of frame
    layer  : must already exist (call dxf_layers.setup_layers(doc) first)
    """
    ox, oy = origin
    pts = get_profile_points_normalised()
    poly_pts = [(x + ox, y + oy) for (x, y) in pts]

    msp.add_lwpolyline(
        poly_pts,
        close=True,
        dxfattribs={"layer": layer, "lineweight": 50},
    )

    minx, miny, maxx, maxy = get_bbox()
    W = maxx - minx
    H = maxy - miny

    dim_attribs = {"layer": "DIMENSIONS"}
    dim_override = {
        "dimtxt": 4.5, "dimasz": 3.2, "dimexe": 1.8, "dimexo": 1.2,
        "dimdec": 1, "dimclrt": 1, "dimclrd": 1, "dimclre": 1,
    }

    dim = msp.add_aligned_dim(
        p1=(ox, oy - 10), p2=(ox + W, oy - 10),
        distance=0, dxfattribs=dim_attribs, override=dim_override,
    )
    dim.render()

    dim = msp.add_aligned_dim(
        p1=(ox - 10, oy), p2=(ox - 10, oy + H),
        distance=0, dxfattribs=dim_attribs, override=dim_override,
    )
    dim.render()

    return poly_pts