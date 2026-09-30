"""Stage 3 tests: full window (frame + mullion + transom + beads).

Run from the project root:
    python -m unittest step_generator.test_stage3 -v
"""
import tempfile
import unittest
from pathlib import Path

from . import config
from .generate_window import WindowGenerationError, generate_window_step

WIDTH = 1200.0
HEIGHT = 1400.0
EXPECTED_PARTS = 4 + 1 + 2 + 16  # frame + mullion + transoms + 4 beads x 4 openings
TOL = 0.05


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "window.step"
        cls.report = generate_window_step(WIDTH, HEIGHT, out_path=cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_step_written_and_valid(self):
        self.assertTrue(self.out.is_file())
        self.assertTrue(self.report["ok"])
        self.assertTrue(self.report["step_validation"]["ok"], self.report["step_validation"]["errors"])

    def test_part_count(self):
        self.assertEqual(self.report["part_count"], EXPECTED_PARTS)
        self.assertEqual(self.report["step_validation"]["checks"]["solids"], EXPECTED_PARTS)

    def test_all_part_names_present(self):
        names = set(self.report["parts"])
        for required in ("Head", "Sill", "Jamb_Left", "Jamb_Right", "Mullion",
                         "Transom_Left", "Transom_Right"):
            self.assertIn(required, names)
        beads = [n for n in names if n.startswith("Bead_")]
        self.assertEqual(len(beads), 16)

    def test_no_overlaps(self):
        for key, volume in self.report["overlaps"].items():
            self.assertLess(volume, 1e-3, key)

    def test_all_parts_positive_volume(self):
        for name, info in self.report["parts"].items():
            self.assertGreater(info["volume"], 0.0, name)

    def test_overall_size(self):
        dims = self.report["step_validation"]["checks"]["overall_xy"]
        self.assertAlmostEqual(dims[0], WIDTH, delta=config.FRAME_BBOX_TOLERANCE)
        self.assertAlmostEqual(dims[1], HEIGHT, delta=config.FRAME_BBOX_TOLERANCE)

    def test_mullion_is_centred_and_spans_opening(self):
        # The mullion may reach into a stepped head / sill face to close the gap,
        # so its ends may extend past the inner faces but never past the frame.
        bb = self.report["parts"]["Mullion"]["bbox"]
        centre = (bb["x"][0] + bb["x"][1]) / 2.0
        self.assertAlmostEqual(centre, WIDTH * config.MULLION_X_FRACTION, delta=TOL)
        across = self.report["across"]
        self.assertLessEqual(bb["y"][0], across["Sill"] + TOL)
        self.assertGreaterEqual(bb["y"][0], -TOL)
        self.assertGreaterEqual(bb["y"][1], HEIGHT - across["Head"] - TOL)
        self.assertLessEqual(bb["y"][1], HEIGHT + TOL)

    def test_transom_height(self):
        bb = self.report["parts"]["Transom_Left"]["bbox"]
        centre = (bb["y"][0] + bb["y"][1]) / 2.0
        self.assertAlmostEqual(centre, HEIGHT * config.TRANSOM_Y_FRACTION, delta=TOL)

    def test_transoms_meet_jambs_and_mullion(self):
        # Each transom must reach its neighbour's face (no gap). It may extend
        # into a stepped neighbour, but never past that neighbour's far side.
        across = self.report["across"]
        mull = self.report["parts"]["Mullion"]["bbox"]["x"]
        left = self.report["parts"]["Transom_Left"]["bbox"]["x"]
        right = self.report["parts"]["Transom_Right"]["bbox"]["x"]

        self.assertLessEqual(left[0], across["Jamb_Left"] + TOL)
        self.assertGreaterEqual(left[0], -TOL)
        self.assertGreaterEqual(left[1], mull[0] - TOL)
        self.assertLessEqual(left[1], mull[1] + TOL)

        self.assertLessEqual(right[0], mull[1] + TOL)
        self.assertGreaterEqual(right[0], mull[0] - TOL)
        self.assertGreaterEqual(right[1], WIDTH - across["Jamb_Right"] - TOL)
        self.assertLessEqual(right[1], WIDTH + TOL)


class WindowRejectionTests(unittest.TestCase):
    def test_opening_too_small_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WindowGenerationError):
                generate_window_step(140.0, HEIGHT, out_path=Path(tmp) / "w.step")

    def test_missing_sections_dir_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WindowGenerationError):
                generate_window_step(WIDTH, HEIGHT, out_path=Path(tmp) / "w.step",
                                     sections_dir=Path(tmp) / "nope")


if __name__ == "__main__":
    unittest.main()
