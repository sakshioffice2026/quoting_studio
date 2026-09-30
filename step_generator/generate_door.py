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
from .assembly_validator import validate_before_export, validate_step_file
from .door_builder import build_door
from .frame_builder import FrameBuildError


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
    """Re-import the STEP and validate it in the exported orientation.

    Z_UP export: X = width, Z = height, and the door depth runs toward -Y with the
    front face at Y = 0. The shared validator expects the frame origin at (0, 0) in
    X-Y, so its origin check is replaced here by the checks that fit Z_UP.
    """
    if door_config.EXPORT_ORIENTATION != "Z_UP":
        return validate_step_file(path, parts, width, height)

    tol = config.FRAME_BBOX_TOLERANCE
    boxes = [p.BoundingBox() for p in parts.values()]
    depth = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)

    report = validate_step_file(path, parts, width, depth)
    report["errors"] = [e for e in report["errors"]
                        if not e.startswith("Frame origin not at outer corner")]
    report["checks"]["orientation"] = "Z_UP"
    if report["errors"]:
        report["ok"] = False
        return report

    solids = cq.importers.importStep(str(path)).solids().vals()
    imported = [s.BoundingBox() for s in solids]
    x_min = min(b.xmin for b in imported)
    y_max = max(b.ymax for b in imported)
    z_min = min(b.zmin for b in imported)
    z_len = max(b.zmax for b in imported) - z_min
    report["checks"]["overall_z"] = z_len
    report["checks"]["origin_xz"] = (x_min, z_min)
    report["checks"]["front_face_y"] = y_max

    if abs(z_len - height) > tol:
        report["errors"].append(f"Overall height (Z) {z_len:.3f} vs {height}")
    if abs(x_min) > tol or abs(z_min) > tol:
        report["errors"].append(
            f"Door origin not at outer bottom-left corner (xmin = {x_min:.3f}, zmin = {z_min:.3f})")
    if y_max > tol:
        report["errors"].append(f"Door extends in front of the front face (ymax = {y_max:.3f})")

    report["ok"] = not report["errors"]
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

    pre = validate_before_export(parts, width, height)
    report["pre_export_validation"] = pre
    report["overlaps"] = pre["overlaps"]
    report["interference_pairs_checked"] = pre["pairs_checked"]
    report.setdefault("warnings", []).extend(pre["warnings"])
    if not pre["ok"]:
        raise DoorGenerationError("Pre-export validation failed: " + "; ".join(pre["errors"]), report)

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
