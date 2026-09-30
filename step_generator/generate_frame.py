"""Stage 2 + 5: mitred frame -> one validated STEP with 4 named parts.

Run from the project root:
    python -m step_generator.generate_frame --width 1000 --height 1200
"""
import argparse
import json
import sys
from pathlib import Path

import cadquery as cq

from . import config
from .assembly_validator import validate_before_export, validate_step_file
from .frame_builder import PART_ORDER, FrameBuildError, build_frame


class FrameGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _export(parts, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="Frame")
    for name in PART_ORDER:
        assembly.add(parts[name], name=name)
    assembly.save(str(out_path), exportType="STEP")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise IOError(f"STEP export produced no file: {out_path}")
    return out_path


def generate_frame_step(width=config.DEFAULT_FRAME_WIDTH, height=config.DEFAULT_FRAME_HEIGHT,
                        out_path=None, sections_dir=None):
    if out_path is None:
        out_path = config.OUTPUT_DIR / config.FRAME_OUTPUT_NAME.format(w=int(width), h=int(height))
    out_path = Path(out_path)

    try:
        parts, report = build_frame(width, height, sections_dir=sections_dir)
    except FrameBuildError as exc:
        raise FrameGenerationError(f"Build error: {exc}", exc.report)

    parts = {name: parts[name] for name in PART_ORDER}
    report["step"] = str(out_path)

    pre = validate_before_export(parts, width, height)
    report["pre_export_validation"] = pre
    report["overlaps"] = pre["overlaps"]
    report["warnings"].extend(pre["warnings"])
    if not pre["ok"]:
        raise FrameGenerationError("Pre-export validation failed: " + "; ".join(pre["errors"]), report)

    try:
        _export(parts, out_path)
    except Exception as exc:
        raise FrameGenerationError(f"STEP export failed: {exc}", report)

    file_report = validate_step_file(out_path, parts, width, height)
    report["step_validation"] = file_report
    if not file_report["ok"]:
        out_path.unlink(missing_ok=True)
        raise FrameGenerationError(
            "STEP re-import check failed: " + "; ".join(file_report["errors"]), report)

    report["ok"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a mitred frame STEP from section DXFs")
    parser.add_argument("--width", type=float, default=config.DEFAULT_FRAME_WIDTH, help="Outer frame width in mm")
    parser.add_argument("--height", type=float, default=config.DEFAULT_FRAME_HEIGHT, help="Outer frame height in mm")
    parser.add_argument("--out", default=None, help="Output .step path")
    parser.add_argument("--sections", default=None, help="Folder containing head/sill/jamb DXFs")
    args = parser.parse_args(argv)

    try:
        report = generate_frame_step(args.width, args.height, out_path=args.out, sections_dir=args.sections)
    except FrameGenerationError as exc:
        print(json.dumps(exc.report, indent=2, default=str))
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, default=str))
    print(f"OK: {report['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
