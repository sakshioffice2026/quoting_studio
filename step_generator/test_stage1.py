"""Stage 1 tests. Run from the project root:
    python -m unittest step_generator.test_stage1 -v
"""
import math
import tempfile
import unittest
from pathlib import Path

import ezdxf

from . import config
from .generate_section import StepGenerationError, generate_section_step


def _write_dxf(path, build):
    doc = ezdxf.new("R2010")
    build(doc.modelspace())
    doc.saveas(str(path))


class RepoSectionTests(unittest.TestCase):
    def test_all_repo_sections(self):
        if not config.SECTIONS_DIR.is_dir():
            self.skipTest(f"Sections folder not found: {config.SECTIONS_DIR}")
        files = sorted(config.SECTIONS_DIR.glob("*.dxf"))
        self.assertTrue(files, "No section DXFs found")
        for dxf in files:
            with self.subTest(section=dxf.name):
                report = generate_section_step(dxf, length=1000.0)
                self.assertTrue(report["ok"])
                self.assertTrue(Path(report["step"]).is_file())


class SyntheticShapeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, name, build, length):
        dxf = self.tmp / f"{name}.dxf"
        _write_dxf(dxf, build)
        return generate_section_step(dxf, length=length, out_path=self.tmp / f"{name}.step")

    def test_rectangle_with_hole(self):
        def build(msp):
            msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
            msp.add_lwpolyline([(10, 10), (90, 10), (90, 50), (10, 50)], close=True)

        report = self._run("rect_hole", build, 200.0)
        expected = (100 * 60 - 80 * 40) * 200.0
        self.assertAlmostEqual(report["solid_validation"]["checks"]["volume"], expected, delta=expected * 1e-3)
        self.assertEqual(report["profile"]["holes"], 1)

    def test_tube_from_circles(self):
        def build(msp):
            msp.add_circle((0, 0), 30)
            msp.add_circle((0, 0), 20)

        report = self._run("tube", build, 500.0)
        expected = math.pi * (30 ** 2 - 20 ** 2) * 500.0
        self.assertAlmostEqual(report["solid_validation"]["checks"]["volume"], expected, delta=expected * 1e-3)

    def test_bulge_circle(self):
        def build(msp):
            msp.add_lwpolyline([(0, 0, 0, 0, 1), (10, 0, 0, 0, 1)], format="xyseb", close=True)

        report = self._run("bulge_circle", build, 100.0)
        expected = math.pi * 5 ** 2 * 100.0
        self.assertAlmostEqual(report["solid_validation"]["checks"]["volume"], expected, delta=expected * 2e-3)

    def test_lines_and_arc_chain(self):
        # Stadium shape from separate LINE + ARC entities (needs edge chaining).
        def build(msp):
            msp.add_line((0, 0), (40, 0))
            msp.add_arc((40, 10), 10, -90, 90)
            msp.add_line((40, 20), (0, 20))
            msp.add_arc((0, 10), 10, 90, 270)

        report = self._run("stadium", build, 300.0)
        expected = (40 * 20 + math.pi * 10 ** 2) * 300.0
        self.assertAlmostEqual(report["solid_validation"]["checks"]["volume"], expected, delta=expected * 2e-3)

    def test_lone_open_polyline_is_autoclosed_with_warning(self):
        def build(msp):
            msp.add_lwpolyline([(0, 0), (0, 20), (50, 20), (50, 0), (12, 0)], close=False)

        report = self._run("open_poly", build, 100.0)
        expected = (50 * 20) * 100.0
        self.assertAlmostEqual(report["solid_validation"]["checks"]["volume"], expected, delta=expected * 1e-3)
        self.assertEqual(len(report["profile"]["warnings"]), 1)

    def test_open_outline_rejected(self):
        def build(msp):
            msp.add_line((0, 0), (50, 0))
            msp.add_line((50, 0), (50, 50))
            msp.add_line((50, 50), (0, 50))

        dxf = self.tmp / "open.dxf"
        _write_dxf(dxf, build)
        with self.assertRaises(StepGenerationError):
            generate_section_step(dxf, length=100.0, out_path=self.tmp / "open.step")

    def test_two_separate_shapes_rejected(self):
        def build(msp):
            msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
            msp.add_lwpolyline([(100, 0), (110, 0), (110, 10), (100, 10)], close=True)

        dxf = self.tmp / "two.dxf"
        _write_dxf(dxf, build)
        with self.assertRaises(StepGenerationError):
            generate_section_step(dxf, length=100.0, out_path=self.tmp / "two.step")


if __name__ == "__main__":
    unittest.main()
