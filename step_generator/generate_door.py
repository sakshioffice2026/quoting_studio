"""Door assembly (L16 double door) -> one validated STEP with named parts.

Run from the project root:
    python -m step_generator.generate_door --width 1800 --height 2100
"""
import argparse
import json
import sys
from pathlib import Path

import cadquery as cq

from . import config, door_config
from .door_builder import build_door
from .frame_builder import FrameBuildError
from .generate_window import _check_interference, _validate_step


class DoorGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _export(parts, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="Door")
    for name, solid in parts.items():
        assembly.add(solid, name=name)
    assembly.save(str(out_path), exportType="STEP")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise IOError(f"STEP export produced no file: {out_path}")
    return out_path


def _orient(parts):
    """Build coordinates (Y = height, Z = depth) -> upright CAD coordinates (Z = height)."""
    if door_config.EXPORT_ORIENTATION != "Z_UP":
        return parts
    origin, axis = cq.Vector(0.0, 0.0, 0.0), cq.Vector(1.0, 0.0, 0.0)
    return {name: solid.rotate(origin, axis, 90.0) for name, solid in parts.items()}


def _validate_oriented_step(path, parts, width, height):
    """Re-import the STEP and check the overall size in the exported orientation."""
    if door_config.EXPORT_ORIENTATION != "Z_UP":
        return _validate_step(path, parts, width, height)

    boxes = [p.BoundingBox() for p in parts.values()]
    depth = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)
    report = _validate_step(path, parts, width, depth)

    solids = cq.importers.importStep(str(path)).solids().vals()
    imported = [s.BoundingBox() for s in solids]
    z_len = max(b.zmax for b in imported) - min(b.zmin for b in imported)
    report["checks"]["overall_z"] = z_len
    report["checks"]["orientation"] = "Z_UP"
    if abs(z_len - height) > config.FRAME_BBOX_TOLERANCE:
        report["errors"].append(f"Overall height (Z) {z_len:.3f} vs {height}")
        report["ok"] = False
    return report


def generate_door_step(width=door_config.DEFAULT_DOOR_WIDTH, height=door_config.DEFAULT_DOOR_HEIGHT,
                       out_path=None, sections=None):
    if out_path is None:
        out_path = config.OUTPUT_DIR / door_config.DOOR_OUTPUT_NAME.format(w=int(width), h=int(height))
    out_path = Path(out_path)

    try:
        parts, report = build_door(width, height, sections=sections)
    except FrameBuildError as exc:
        raise DoorGenerationError(f"Build error: {exc}", exc.report)

    report["step"] = str(out_path)
    report["part_count"] = len(parts)

    overlaps, errors, checked = _check_interference(parts, report)
    report["overlaps"] = overlaps
    report["interference_pairs_checked"] = checked
    if errors:
        raise DoorGenerationError("Door fit check failed: " + "; ".join(errors), report)

    export_parts = _orient(parts)
    report["orientation"] = door_config.EXPORT_ORIENTATION

    try:
        _export(export_parts, out_path)
    except Exception as exc:
        raise DoorGenerationError(f"STEP export failed: {exc}", report)

    file_report = _validate_oriented_step(out_path, export_parts, width, height)
    report["step_validation"] = file_report
    if not file_report["ok"]:
        out_path.unlink(missing_ok=True)
        raise DoorGenerationError(
            "STEP re-import check failed: " + "; ".join(file_report["errors"]), report)

    report["ok"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate an L16 double door STEP from section DXFs")
    parser.add_argument("--width", type=float, default=door_config.DEFAULT_DOOR_WIDTH, help="Outer door width in mm")
    parser.add_argument("--height", type=float, default=door_config.DEFAULT_DOOR_HEIGHT, help="Outer door height in mm")
    parser.add_argument("--out", default=None, help="Output .step path")
    args = parser.parse_args(argv)

    try:
        report = generate_door_step(args.width, args.height, out_path=args.out)
    except DoorGenerationError as exc:
        print(json.dumps(exc.report, indent=2, default=str))
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, default=str))
    print(f"OK: {report['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
