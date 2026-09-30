"""Stage 5 tests: validation of every export.

Run from the project root:
    python -m pytest step_generator/test_stage5.py
"""
import cadquery as cq
import pytest

from step_generator import config
from step_generator.assembly_validator import (
    check_overall_bbox,
    check_overlaps,
    check_parts,
    validate_before_export,
    validate_step_file,
)
from step_generator.frame_builder import build_frame
from step_generator.generate_frame import generate_frame_step
from step_generator.generate_window import generate_window_step
from step_generator.window_builder import build_window

W = 1000.0
H = 1200.0


def _box(x, y, z, dx, dy, dz):
    return (
        cq.Workplane("XY")
        .box(dx, dy, dz, centered=False)
        .translate((x, y, z))
        .val()
    )


def test_frame_passes_pre_export():
    parts, _ = build_frame(W, H)
    report = validate_before_export(parts, W, H)
    assert report["ok"], report["errors"]


def test_window_passes_pre_export():
    parts, _ = build_window(W, H)
    report = validate_before_export(parts, W, H)
    assert report["ok"], report["errors"]


def test_overlap_detected():
    parts = {
        "A": _box(0, 0, 0, 100, 100, 10),
        "B": _box(50, 50, 0, 100, 100, 10),
    }
    overlaps, errors, checked, _ = check_overlaps(parts)
    assert checked == 1
    assert "A+B" in overlaps
    assert errors


def test_touching_faces_allowed():
    parts = {
        "A": _box(0, 0, 0, 100, 100, 10),
        "B": _box(100, 0, 0, 100, 100, 10),
    }
    _, errors, _, _ = check_overlaps(parts)
    assert not errors


def test_part_outside_frame_detected():
    parts = {"A": _box(0, 0, 0, 1200, 100, 10)}
    _, errors = check_parts(parts, W, H)
    assert any("outside frame bounds" in e for e in errors)


def test_overall_bbox_mismatch_detected():
    parts = {"A": _box(0, 0, 0, 900, 1200, 10)}
    _, errors = check_overall_bbox(list(parts.values()), W, H)
    assert errors


def test_part_in_front_of_face_detected():
    parts = {"A": _box(0, 0, -5, 100, 100, 10)}
    _, errors = check_parts(parts, W, H)
    assert any("front face" in e for e in errors)


def test_missing_step_file_detected(tmp_path):
    parts = {"A": _box(0, 0, 0, 100, 100, 10)}
    report = validate_step_file(tmp_path / "missing.step", parts, 100, 100)
    assert not report["ok"]


def test_step_solid_count_mismatch_detected(tmp_path):
    a = _box(0, 0, 0, 100, 100, 10)
    path = tmp_path / "one.step"
    assembly = cq.Assembly(name="T")
    assembly.add(a, name="A")
    assembly.save(str(path), exportType="STEP")
    parts = {"A": a, "B": _box(200, 0, 0, 50, 50, 10)}
    report = validate_step_file(path, parts, 250, 100)
    assert not report["ok"]


def test_generate_frame_step_validates(tmp_path):
    out = tmp_path / "frame.step"
    report = generate_frame_step(W, H, out_path=out)
    assert report["ok"]
    assert report["step_validation"]["ok"]
    assert out.is_file()


def test_generate_window_step_validates(tmp_path):
    out = tmp_path / "window.step"
    report = generate_window_step(W, H, out_path=out)
    assert report["ok"]
    assert report["step_validation"]["ok"]
    assert out.is_file()


@pytest.mark.parametrize("width,height", [(900.0, 1100.0), (1500.0, 1400.0)])
def test_multiple_sizes(tmp_path, width, height):
    out = tmp_path / f"window_{int(width)}x{int(height)}.step"
    report = generate_window_step(width, height, out_path=out)
    assert report["ok"]
    overall = report["step_validation"]["checks"]["overall_xy"]
    assert abs(overall[0] - width) <= config.FRAME_BBOX_TOLERANCE
    assert abs(overall[1] - height) <= config.FRAME_BBOX_TOLERANCE
