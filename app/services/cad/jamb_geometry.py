"""
Jamb (vertical side) member geometry — real traced profile, standalone test only.

NOT wired into frame_assembly.py / model3d.py / model3d_freecad.py.

Profile source: app/cad_sections/cad_sections/jamb.dxf
Single closed LWPOLYLINE, 66 vertices, no duplicates detected.
Bounding box: 67.0 x 90.0 mm.

Convention (matches model3d_freecad._mk_face plane='V'):
    Local axes: X = across profile (67mm), Y = depth through wall (90mm).
    Extrusion: +Y direction for height_mm (vertical member).
    FreeCAD mapping: (u, v) -> V(u, 0.0, v), extrude V(0, height_mm, 0).
"""

PROFILE_NAME = "Jamb_VerticalSideMember"

# Verbatim (x, y) vertices from jamb.dxf, in order, closed. 66 vertices.
JAMB_PROFILE_POINTS = [
    (62.118, 14.529),
    (63.618, 16.029),
    (63.618, 19.079),
    (63.218, 19.569),
    (63.218, 23.488),
    (63.618, 23.978),
    (63.618, 51.538),
    (64.609, 52.538),
    (70.627, 52.590),
    (71.618, 53.590),
    (71.618, 55.223),
    (71.361, 55.660),
    (69.213, 58.028),
    (63.118, 58.028),
    (63.118, 62.028),
    (69.213, 62.028),
    (71.361, 64.395),
    (71.618, 64.832),
    (71.618, 74.229),
    (64.618, 74.229),
    (64.618, 78.229),
    (71.895, 78.229),
    (72.609, 78.538),
    (82.627, 78.625),
    (83.618, 79.625),
    (83.618, 95.520),
    (82.627, 96.520),
    (81.835, 96.527),
    (81.553, 96.732),
    (73.903, 102.520),
    (73.618, 102.820),
    (73.618, 103.529),
    (72.618, 104.529),
    (27.618, 104.529),
    (26.618, 103.529),
    (26.618, 102.820),
    (26.332, 102.520),
    (18.683, 96.732),
    (18.401, 96.527),
    (17.609, 96.520),
    (16.618, 95.520),
    (16.618, 79.625),
    (17.609, 78.625),
    (27.627, 78.538),
    (28.340, 78.229),
    (35.618, 78.229),
    (35.618, 74.229),
    (28.618, 74.229),
    (28.618, 64.832),
    (28.875, 64.395),
    (31.023, 62.028),
    (37.118, 62.028),
    (37.118, 58.028),
    (31.023, 58.028),
    (28.875, 55.660),
    (28.618, 55.223),
    (28.618, 53.590),
    (29.609, 52.590),
    (35.627, 52.538),
    (36.618, 51.538),
    (36.618, 23.978),
    (37.018, 23.488),
    (37.018, 19.569),
    (36.618, 19.079),
    (36.618, 16.029),
    (38.118, 14.529),
]


def get_bbox():
    xs = [p[0] for p in JAMB_PROFILE_POINTS]
    ys = [p[1] for p in JAMB_PROFILE_POINTS]
    return min(xs), min(ys), max(xs), max(ys)


def get_jamb_bbox():
    return get_bbox()


def get_profile_points_normalised():
    """Profile shifted so its bounding box starts at (0, 0)."""
    minx, miny, _, _ = get_bbox()
    return [(round(x - minx, 3), round(y - miny, 3)) for (x, y) in JAMB_PROFILE_POINTS]


def draw_jamb_section(msp, origin=(0.0, 0.0), layer="FRAME_GEOMETRY"):
    """
    Draw the jamb cross-section as a closed LWPOLYLINE on `layer`,
    plus overall width/height dimensions.
    Natural orientation: X = across (67mm), Y = depth (90mm).

    msp    : ezdxf modelspace
    origin : (x, y) offset for the section drawing
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
