"""
Head (top horizontal) member geometry — PLACEHOLDER, standalone test only.

NOT wired into frame_assembly.py / model3d.py / model3d_freecad.py.

Software fact: no real head-section DXF has been supplied yet. This
reuses the same traced points as threshold_geometry.py
(THRESHOLD_PROFILE_POINTS, bbox 165 x 60mm) purely to test the
plane-ZX + Y-offset-to-H extrusion logic end-to-end. Replace
HEAD_PROFILE_POINTS with a real traced head-section DXF before this
represents an actual head member.
"""
from app.services.threshold_geometry import get_profile_points_normalised, get_bbox

PROFILE_NAME = "Head_Placeholder_ReusedThresholdSection"

# Placeholder only — same digitised points as the threshold section,
# reused here just to exercise the ZX-plane / Y=H offset path.
HEAD_PROFILE_POINTS = get_profile_points_normalised()


def get_head_bbox():
    return get_bbox()


def draw_head_section(msp, origin=(0.0, 0.0), layer="WINDOW_CILL"):
    """
    Draw the head cross-section (same points as threshold, placeholder)
    as a closed LWPOLYLINE on `layer`, plus overall width/height
    dimensions, using the same msp.add_aligned_dim(...).render()
    pattern as engineering_dxf.py / threshold_geometry.py.

    msp: ezdxf modelspace
    origin: (x, y) offset to draw at — pass (0, H_mm) to draw the
            section at the head's Y-offset position.
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

    minx, miny, maxx, maxy = get_head_bbox()
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