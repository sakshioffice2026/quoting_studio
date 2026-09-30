"""Stage 3 batch tests: every section DXF in the repo.

Run from the project root:
    python -m unittest step_generator.test_stage3_sections -v
"""
import tempfile
import unittest
from pathlib import Path

from . import config
from .dxf_profile import load_profile, load_profiles
from .generate_all_sections import find_section_dxfs, generate_all_sections
from .generate_section import generate_section_steps


class AllSectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.summary = generate_all_sections(out_dir=Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_sections_found(self):
        self.assertGreater(self.summary["total"], 0)
        names = {Path(r["dxf"]).name for r in self.summary["sections"]}
        for required in ("head.dxf", "sill.dxf", "jamb.dxf", "meeting_stile.dxf",
                         "glazing_bar.dxf", "bead.dxf"):
            self.assertIn(required, names)

    def test_no_backup_files_processed(self):
        for row in self.summary["sections"]:
            self.assertFalse(row["dxf"].lower().endswith(config.SECTION_SKIP_SUFFIXES), row["dxf"])

    def test_every_section_generates(self):
        failures = [f"{r['name']}: {r['error']}" for r in self.summary["sections"] if not r["ok"]]
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_output_names_unique(self):
        names = [r["name"].lower() for r in self.summary["sections"]]
        self.assertEqual(len(names), len(set(names)))

    def test_step_files_written(self):
        for row in self.summary["sections"]:
            if row["ok"]:
                self.assertEqual(len(row["steps"]), row["shapes"], row["name"])
                for step in row["steps"]:
                    path = Path(step)
                    self.assertTrue(path.is_file(), step)
                    self.assertGreater(path.stat().st_size, 0, step)

    def test_positive_volume_and_size(self):
        for row in self.summary["sections"]:
            if row["ok"]:
                self.assertGreater(row["volume"], 0.0, row["name"])
                self.assertGreater(row["across"], 0.0, row["name"])
                self.assertGreater(row["depth"], 0.0, row["name"])

    def test_one_origin_convention(self):
        """Every profile sits with its bounding-box corner at the origin."""
        for _, dxf in find_section_dxfs():
            try:
                profile = load_profile(dxf, normalize_origin=True)
            except Exception:
                continue  # reported by test_every_section_generates
            min_x, min_y, max_x, max_y = profile.outer.bbox()
            self.assertAlmostEqual(min_x, 0.0, delta=config.BBOX_TOLERANCE, msg=str(dxf))
            self.assertAlmostEqual(min_y, 0.0, delta=config.BBOX_TOLERANCE, msg=str(dxf))
            self.assertAlmostEqual(max_x, profile.width, delta=config.BBOX_TOLERANCE, msg=str(dxf))
            self.assertAlmostEqual(max_y, profile.height, delta=config.BBOX_TOLERANCE, msg=str(dxf))


class SyntheticDxfTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, build):
        import ezdxf
        doc = ezdxf.new("R2010")
        build(doc)
        path = self.tmp / name
        doc.saveas(str(path))
        return path

    def test_block_reference_is_exploded(self):
        def build(doc):
            block = doc.blocks.new("PART")
            block.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True)
            doc.modelspace().add_blockref("PART", (5000.0, -3000.0))

        dxf = self._write("block.dxf", build)
        profile = load_profile(dxf)
        self.assertAlmostEqual(profile.width, 40.0, delta=1e-6)
        self.assertAlmostEqual(profile.height, 20.0, delta=1e-6)

    def test_nested_block_reference_is_exploded(self):
        def build(doc):
            inner = doc.blocks.new("INNER")
            inner.add_lwpolyline([(0, 0), (30, 0), (30, 10), (0, 10)], close=True)
            outer = doc.blocks.new("OUTER")
            outer.add_blockref("INNER", (100.0, 100.0))
            doc.modelspace().add_blockref("OUTER", (-500.0, 250.0))

        dxf = self._write("nested.dxf", build)
        profile = load_profile(dxf)
        self.assertAlmostEqual(profile.width, 30.0, delta=1e-6)
        self.assertAlmostEqual(profile.height, 10.0, delta=1e-6)

    def test_dashed_construction_line_is_ignored(self):
        def build(doc):
            doc.linetypes.add("DASHED", pattern=[0.5, 0.25, -0.25])
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)], close=True)
            msp.add_lwpolyline([(10, -5), (40, -5), (40, 35), (10, 35)], close=True,
                               dxfattribs={"linetype": "DASHED"})

        dxf = self._write("dashed.dxf", build)
        profile = load_profile(dxf)
        self.assertAlmostEqual(profile.width, 50.0, delta=1e-6)
        self.assertAlmostEqual(profile.height, 30.0, delta=1e-6)
        self.assertTrue(any("construction_linetype" in k for k in profile.skipped))

    def test_two_shapes_export_as_two_solids(self):
        def build(doc):
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
            msp.add_lwpolyline([(100, 0), (130, 0), (130, 20), (100, 20)], close=True)

        dxf = self._write("two.dxf", build)
        profiles = load_profiles(dxf)
        self.assertEqual(len(profiles), 2)
        self.assertAlmostEqual(profiles[0].width, 10.0, delta=1e-6)
        self.assertAlmostEqual(profiles[1].width, 30.0, delta=1e-6)

        reports = generate_section_steps(dxf, length=100.0, out_dir=self.tmp)
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertTrue(report["ok"])
            self.assertTrue(Path(report["step"]).is_file())
        self.assertNotEqual(reports[0]["step"], reports[1]["step"])

    def test_hole_stays_with_its_own_shape(self):
        def build(doc):
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
            msp.add_circle((50, 50), 10)
            msp.add_lwpolyline([(300, 0), (340, 0), (340, 40), (300, 40)], close=True)

        dxf = self._write("hole_two.dxf", build)
        profiles = load_profiles(dxf)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(len(profiles[0].holes), 1)
        self.assertEqual(len(profiles[1].holes), 0)


class WindowWarningTests(unittest.TestCase):
    def test_profile_warnings_reach_window_report(self):
        from .window_builder import build_window

        _, report = build_window(1200.0, 1400.0)
        warned = [w for w in report["warnings"] if w.startswith("meeting_stile.dxf")]
        self.assertTrue(warned, "meeting_stile.dxf auto-close warning missing from window report")


if __name__ == "__main__":
    unittest.main()
