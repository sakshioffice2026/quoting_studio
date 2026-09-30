"""Orientation tests: every member on one convention.

    across = distance inward from the outer edge of the frame
    depth  = distance from the front / exterior face (z = 0) toward the interior

Run from the project root:
    python -m pytest step_generator/test_orientation.py
"""
import cadquery as cq

from step_generator.frame_builder import build_frame
from step_generator.window_builder import build_window

W = 1000.0
H = 1200.0
TOL = 0.05


def _slab(solid, z0, z1):
    box = (
        cq.Workplane("XY")
        .box(W * 2, H * 2, z1 - z0, centered=(True, True, False))
        .translate((W / 2, H / 2, z0))
        .val()
    )
    common = solid.intersect(box)
    return common.BoundingBox()


def test_all_members_start_at_front_face():
    parts, _ = build_frame(W, H)
    for name, solid in parts.items():
        assert abs(solid.BoundingBox().zmin) <= TOL, name


def test_depth_matches_drawn_depth():
    parts, report = build_frame(W, H)
    for name, solid in parts.items():
        assert abs(solid.BoundingBox().zlen - report["depth"][name]) <= TOL, name


def test_head_jambs_share_depth():
    _, report = build_frame(W, H)
    d = report["depth"]
    assert abs(d["Head"] - d["Jamb_Left"]) <= TOL
    assert abs(d["Jamb_Left"] - d["Jamb_Right"]) <= TOL


def test_across_is_visible_face_width():
    parts, report = build_frame(W, H)
    a = report["across"]
    assert abs(parts["Head"].BoundingBox().ylen - a["Head"]) <= TOL
    assert abs(parts["Sill"].BoundingBox().ylen - a["Sill"]) <= TOL
    assert abs(parts["Jamb_Left"].BoundingBox().xlen - a["Jamb_Left"]) <= TOL
    assert abs(parts["Jamb_Right"].BoundingBox().xlen - a["Jamb_Right"]) <= TOL


def test_head_and_sill_across_is_narrow_side():
    _, report = build_frame(W, H)
    a, d = report["across"], report["depth"]
    assert a["Head"] < d["Head"]
    assert a["Sill"] < d["Sill"]
    assert a["Jamb_Left"] < d["Jamb_Left"]


def test_sill_falls_toward_front_face():
    parts, report = build_frame(W, H)
    sill = parts["Sill"]
    depth = report["depth"]["Sill"]
    front = _slab(sill, 0.0, 10.0)
    back = _slab(sill, depth - 30.0, depth)
    assert front.ymax < back.ymax


def test_mullion_across_is_narrow_side():
    parts, report = build_window(W, H)
    bb = parts["Mullion"].BoundingBox()
    assert bb.xlen < bb.zlen
    assert abs(bb.zmin) <= TOL
    assert report["parts"]["Mullion"]["across"] < report["parts"]["Mullion"]["depth"]
