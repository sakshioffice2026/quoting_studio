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
        bb = self.report["parts"]["Mullion"]["bbox"]
        centre = (bb["x"][0] + bb["x"][1]) / 2.0
        self.assertAlmostEqual(centre, WIDTH * config.MULLION_X_FRACTION, delta=0.05)
        across = self.report["across"]
        self.assertAlmostEqual(bb["y"][0], across["Sill"], delta=0.05)
        self.assertAlmostEqual(bb["y"][1], HEIGHT - across["Head"], delta=0.05)

    def test_transom_height(self):
        bb = self.report["parts"]["Transom_Left"]["bbox"]
        centre = (bb["y"][0] + bb["y"][1]) / 2.0
        self.assertAlmostEqual(centre, HEIGHT * config.TRANSOM_Y_FRACTION, delta=0.05)

    def test_transoms_meet_jambs_and_mullion(self):
        across = self.report["across"]
        mull = self.report["parts"]["Mullion"]["bbox"]["x"]
        left = self.report["parts"]["Transom_Left"]["bbox"]["x"]
        right = self.report["parts"]["Transom_Right"]["bbox"]["x"]
        self.assertAlmostEqual(left[0], across["Jamb_Left"], delta=0.05)
        self.assertAlmostEqual(left[1], mull[0], delta=0.05)
        self.assertAlmostEqual(right[0], mull[1], delta=0.05)
        self.assertAlmostEqual(right[1], WIDTH - across["Jamb_Right"], delta=0.05)


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
