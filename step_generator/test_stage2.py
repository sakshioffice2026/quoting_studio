"""Stage 2 tests. Run from the project root:
    python -m unittest step_generator.test_stage2 -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ezdxf

from . import config
from .frame_builder import FRAME_JOINT, PART_ORDER, FrameBuildError, build_frame
from .generate_frame import FrameGenerationError, generate_frame_step

# Rectangular test sections: (across, depth)
HEAD = (50.0, 30.0)
SILL = (80.0, 40.0)
JAMB = (60.0, 30.0)


def _write_rect(path, across, depth):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (across, 0), (across, depth), (0, depth)], close=True
    )
    doc.saveas(str(path))


def _trapezoid_area(outer, inner, band):
    return (outer + inner) / 2.0 * band


class SyntheticFrameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        _write_rect(self.tmp / "head.dxf", *HEAD)
        _write_rect(self.tmp / "sill.dxf", *SILL)
        _write_rect(self.tmp / "jamb.dxf", *JAMB)

        # Synthetic sections are drawn as (across, depth): no rotation for any part.
        self._patches = [
            mock.patch.dict(config.SECTION_ORIENTATION, {
                "Head": "as_drawn", "Sill": "as_drawn",
                "Jamb_Left": "as_drawn", "Jamb_Right": "as_drawn",
            }),
            mock.patch.object(config, "SECTION_ORIENTATION_BY_FILE", {}, create=True),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    def test_member_volumes_are_exact(self):
        W, H = 1000.0, 1200.0
        parts, report = build_frame(W, H, sections_dir=self.tmp)
        self.assertEqual(list(parts), list(PART_ORDER))

        inner_w = W - 2 * JAMB[0]
        inner_h = H - HEAD[0] - SILL[0]
        if FRAME_JOINT == "butt":
            expected = {
                "Head": W * HEAD[0] * HEAD[1],
                "Sill": W * SILL[0] * SILL[1],
                "Jamb_Left": inner_h * JAMB[0] * JAMB[1],
                "Jamb_Right": inner_h * JAMB[0] * JAMB[1],
            }
        else:
            expected = {
                "Head": _trapezoid_area(W, inner_w, HEAD[0]) * HEAD[1],
                "Sill": _trapezoid_area(W, inner_w, SILL[0]) * SILL[1],
                "Jamb_Left": _trapezoid_area(H, inner_h, JAMB[0]) * JAMB[1],
                "Jamb_Right": _trapezoid_area(H, inner_h, JAMB[0]) * JAMB[1],
            }
        for name, want in expected.items():
            with self.subTest(part=name):
                self.assertAlmostEqual(parts[name].Volume(), want, delta=want * 1e-3)

    @unittest.skipUnless(FRAME_JOINT == "butt", "butt joint only")
    def test_jambs_sit_between_head_and_sill(self):
        W, H = 1000.0, 1200.0
        parts, _ = build_frame(W, H, sections_dir=self.tmp)
        for name in ("Jamb_Left", "Jamb_Right"):
            with self.subTest(part=name):
                bb = parts[name].BoundingBox()
                self.assertAlmostEqual(bb.ymin, SILL[0], delta=1e-3)
                self.assertAlmostEqual(bb.ymax, H - HEAD[0], delta=1e-3)
        for name in ("Head", "Sill"):
            with self.subTest(part=name):
                bb = parts[name].BoundingBox()
                self.assertAlmostEqual(bb.xmin, 0.0, delta=1e-3)
                self.assertAlmostEqual(bb.xmax, W, delta=1e-3)

    def test_members_sit_in_frame_bounds(self):
        W, H = 900.0, 1100.0
        parts, _ = build_frame(W, H, sections_dir=self.tmp)
        for name, solid in parts.items():
            with self.subTest(part=name):
                bb = solid.BoundingBox()
                self.assertGreaterEqual(bb.xmin, -1e-3)
                self.assertGreaterEqual(bb.ymin, -1e-3)
                self.assertLessEqual(bb.xmax, W + 1e-3)
                self.assertLessEqual(bb.ymax, H + 1e-3)
                self.assertGreaterEqual(bb.zmin, -1e-3)

    def test_generate_and_reimport(self):
        out = self.tmp / "frame.step"
        report = generate_frame_step(1000.0, 1200.0, out_path=out, sections_dir=self.tmp)
        self.assertTrue(report["ok"])
        self.assertTrue(out.is_file())
        self.assertEqual(report["step_validation"]["checks"]["solids"], 4)
        self.assertEqual(report["step_validation"]["checks"]["names_missing"], [])
        for pair, overlap in report["overlaps"].items():
            with self.subTest(pair=pair):
                self.assertLess(overlap, 1.0)

    def test_frame_too_narrow_rejected(self):
        with self.assertRaises(FrameBuildError):
            build_frame(100.0, 1200.0, sections_dir=self.tmp)

    def test_frame_too_short_rejected(self):
        with self.assertRaises(FrameBuildError):
            build_frame(1000.0, 100.0, sections_dir=self.tmp)

    def test_missing_section_file_rejected(self):
        (self.tmp / "sill.dxf").unlink()
        with self.assertRaises(FrameBuildError):
            build_frame(1000.0, 1200.0, sections_dir=self.tmp)


class RepoFrameTests(unittest.TestCase):
    def test_repo_sections_frame(self):
        if not config.SECTIONS_DIR.is_dir():
            self.skipTest(f"Sections folder not found: {config.SECTIONS_DIR}")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "frame.step"
            try:
                report = generate_frame_step(1000.0, 1200.0, out_path=out)
            except FrameGenerationError as exc:
                self.fail(f"{exc}\n{exc.report}")
            self.assertTrue(report["ok"])
            self.assertEqual(report["step_validation"]["checks"]["solids"], 4)


if __name__ == "__main__":
    unittest.main()
