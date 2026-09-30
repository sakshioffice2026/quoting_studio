"""Door assembly tests (L16 double door)."""
import tempfile
import unittest
from pathlib import Path

import cadquery as cq

from . import config, door_config
from .door_builder import DoorBuildError, build_door
from .generate_door import generate_door_step

WIDTH = 1800.0
HEIGHT = 2100.0
TOL = config.FRAME_BBOX_TOLERANCE

EXPECTED_NAMES = {
    "Head", "Sill", "Jamb_Left", "Jamb_Right", "Hinge_Center",
    "Base_Rail_Left", "Base_Rail_Right", "Base_Support_Left", "Base_Support_Right",
} | {f"Bead_{c}_{s}" for c in ("Left", "Right") for s in ("Bottom", "Top", "Left", "Right")}


class DoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "door.step"
        cls.report = generate_door_step(WIDTH, HEIGHT, out_path=cls.out)
        cls.parts, cls.build_report = build_door(WIDTH, HEIGHT)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_all_section_files_exist(self):
        for role, path in door_config.L16_DOUBLE_SECTIONS.items():
            self.assertTrue(Path(path).is_file(), f"{role}: {path}")

    def test_sill_is_low_and_deep(self):
        across = self.build_report["across"]["Sill"]
        depth = self.build_report["depth"]["Sill"]
        self.assertLess(across, depth)
        bb = self.parts["Sill"].BoundingBox()
        self.assertAlmostEqual(bb.ymin, 0.0, delta=TOL)
        self.assertAlmostEqual(bb.ymax, across, delta=TOL)
        self.assertAlmostEqual(bb.zlen, depth, delta=TOL)

    def test_all_part_names_present(self):
        self.assertEqual(set(self.parts), EXPECTED_NAMES)

    def test_part_count(self):
        self.assertEqual(len(self.parts), len(EXPECTED_NAMES))
        self.assertEqual(self.report["part_count"], len(EXPECTED_NAMES))

    def test_all_parts_positive_volume(self):
        for name, solid in self.parts.items():
            self.assertGreater(solid.Volume(), 0, name)
            self.assertTrue(solid.isValid(), name)

    def test_no_overlaps(self):
        for key, volume in self.report["overlaps"].items():
            a, b = key.split("+")
            smaller = min(self.parts[a].Volume(), self.parts[b].Volume())
            self.assertLessEqual(volume, smaller * door_config.DOOR_OVERLAP_REL_TOLERANCE, key)

    def test_overall_size(self):
        xs, ys = [], []
        for solid in self.parts.values():
            bb = solid.BoundingBox()
            xs += [bb.xmin, bb.xmax]
            ys += [bb.ymin, bb.ymax]
        self.assertAlmostEqual(max(xs) - min(xs), WIDTH, delta=TOL)
        self.assertAlmostEqual(max(ys) - min(ys), HEIGHT, delta=TOL)

    def test_hinge_is_centred_and_spans_opening(self):
        bb = self.parts["Hinge_Center"].BoundingBox()
        self.assertAlmostEqual((bb.xmin + bb.xmax) / 2.0, WIDTH * door_config.HINGE_X_FRACTION, delta=TOL)
        a = self.build_report["across"]
        self.assertAlmostEqual(bb.ymin, a["Sill"], delta=TOL)
        self.assertAlmostEqual(bb.ymax, HEIGHT - a["Head"], delta=TOL)

    def test_base_members_meet_jambs_and_hinge(self):
        a = self.build_report["across"]
        hinge = self.parts["Hinge_Center"].BoundingBox()
        for name in ("Base_Rail_Left", "Base_Support_Left"):
            bb = self.parts[name].BoundingBox()
            self.assertAlmostEqual(bb.xmin, a["Jamb_Left"], delta=TOL, msg=name)
            self.assertAlmostEqual(bb.xmax, hinge.xmin, delta=TOL, msg=name)
        for name in ("Base_Rail_Right", "Base_Support_Right"):
            bb = self.parts[name].BoundingBox()
            self.assertAlmostEqual(bb.xmin, hinge.xmax, delta=TOL, msg=name)
            self.assertAlmostEqual(bb.xmax, WIDTH - a["Jamb_Right"], delta=TOL, msg=name)

    def test_base_support_sits_on_base_rail(self):
        for col in ("Left", "Right"):
            rail = self.parts[f"Base_Rail_{col}"].BoundingBox()
            support = self.parts[f"Base_Support_{col}"].BoundingBox()
            self.assertAlmostEqual(support.ymin, rail.ymax, delta=TOL, msg=col)

    def test_step_written_and_valid(self):
        self.assertTrue(self.out.is_file())
        self.assertTrue(self.report["step_validation"]["ok"])
        solids = cq.importers.importStep(str(self.out)).solids().vals()
        self.assertEqual(len(solids), len(EXPECTED_NAMES))


class DoorOrientationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "door_upright.step"
        cls.report = generate_door_step(WIDTH, HEIGHT, out_path=cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_exported_door_stands_upright(self):
        self.assertEqual(door_config.EXPORT_ORIENTATION, "Z_UP")
        solids = cq.importers.importStep(str(self.out)).solids().vals()
        boxes = [s.BoundingBox() for s in solids]
        x_len = max(b.xmax for b in boxes) - min(b.xmin for b in boxes)
        y_len = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)
        z_len = max(b.zmax for b in boxes) - min(b.zmin for b in boxes)
        self.assertAlmostEqual(x_len, WIDTH, delta=TOL)
        self.assertAlmostEqual(z_len, HEIGHT, delta=TOL)
        self.assertLess(y_len, 200.0)

    def test_orientation_reported(self):
        self.assertEqual(self.report["orientation"], "Z_UP")


class DoorRejectionTests(unittest.TestCase):
    def test_missing_section_rejected(self):
        with self.assertRaises(DoorBuildError):
            build_door(WIDTH, HEIGHT, sections={"Hinge": Path("missing_section.dxf")})

    def test_opening_too_small_rejected(self):
        with self.assertRaises(DoorBuildError):
            build_door(500.0, HEIGHT)


if __name__ == "__main__":
    unittest.main()
