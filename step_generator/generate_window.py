"""Stage 3 + 5: complete window -> one validated STEP with named parts.

Run from the project root:
    python -m step_generator.generate_window --width 1200 --height 1400
"""
import argparse
import json
import sys
from pathlib import Path

import cadquery as cq

from . import config
from .assembly_validator import validate_before_export, validate_step_file
from .frame_builder import FrameBuildError
from .window_builder import build_window


class WindowGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _export(parts, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="Window")
    for name, solid in parts.items():
        assembly.add(solid, name=name)
    assembly.save(str(out_path), exportType="STEP")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise IOError(f"STEP export produced no file: {out_path}")
    return out_path


def generate_window_step(width=config.DEFAULT_FRAME_WIDTH, height=config.DEFAULT_FRAME_HEIGHT,
                         out_path=None, sections_dir=None):
    if out_path is None:
        out_path = config.OUTPUT_DIR / config.WINDOW_OUTPUT_NAME.format(w=int(width), h=int(height))
    out_path = Path(out_path)

    try:
        parts, report = build_window(width, height, sections_dir=sections_dir)
    except FrameBuildError as exc:
        raise WindowGenerationError(f"Build error: {exc}", exc.report)

    report["step"] = str(out_path)
    report["part_count"] = len(parts)

    pre = validate_before_export(parts, width, height)
    report["pre_export_validation"] = pre
    report["overlaps"] = pre["overlaps"]
    report["interference_pairs_checked"] = pre["pairs_checked"]
    report["warnings"].extend(pre["warnings"])
    if not pre["ok"]:
        raise WindowGenerationError("Pre-export validation failed: " + "; ".join(pre["errors"]), report)

    try:
        _export(parts, out_path)
    except Exception as exc:
        raise WindowGenerationError(f"STEP export failed: {exc}", report)

    file_report = validate_step_file(out_path, parts, width, height)
    report["step_validation"] = file_report
    if not file_report["ok"]:
        out_path.unlink(missing_ok=True)
        raise WindowGenerationError(
            "STEP re-import check failed: " + "; ".join(file_report["errors"]), report)

    report["ok"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a full window STEP from section DXFs")
    parser.add_argument("--width", type=float, default=config.DEFAULT_FRAME_WIDTH, help="Outer frame width in mm")
    parser.add_argument("--height", type=float, default=config.DEFAULT_FRAME_HEIGHT, help="Outer frame height in mm")
    parser.add_argument("--out", default=None, help="Output .step path")
    parser.add_argument("--sections", default=None, help="Folder containing the section DXFs")
    args = parser.parse_args(argv)

    try:
        report = generate_window_step(args.width, args.height, out_path=args.out, sections_dir=args.sections)
    except WindowGenerationError as exc:
        print(json.dumps(exc.report, indent=2, default=str))
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, default=str))
    print(f"OK: {report['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
