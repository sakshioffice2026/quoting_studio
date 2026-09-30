"""Stage 2: mitred frame -> one validated STEP with 4 named parts.

Run from the project root:
    python -m step_generator.generate_frame --width 1000 --height 1200
"""
import argparse
import json
import sys
from pathlib import Path

import cadquery as cq

from . import config
from .frame_builder import PART_ORDER, FrameBuildError, build_frame

ADJACENT_PAIRS = (
    ("Head", "Jamb_Left"),
    ("Head", "Jamb_Right"),
    ("Sill", "Jamb_Left"),
    ("Sill", "Jamb_Right"),
)


class FrameGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _check_interference(parts, report):
    """Adjacent members must touch at the mitre only, never overlap."""
    result = {}
    errors = []
    for a, b in ADJACENT_PAIRS:
        key = f"{a}+{b}"
        try:
            common = parts[a].intersect(parts[b])
            overlap = sum(s.Volume() for s in common.Solids())
        except Exception as exc:
            report["warnings"].append(f"Interference check skipped for {key}: {exc}")
            continue
        smaller = min(parts[a].Volume(), parts[b].Volume())
        result[key] = overlap
        if overlap > smaller * config.FRAME_VOLUME_REL_TOLERANCE:
            errors.append(f"{key} overlap {overlap:.3f} mm3 (mitre does not fit)")
    return result, errors


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


def _validate_step(path, parts, width, height):
    errors = []
    checks = {}

    try:
        imported = cq.importers.importStep(str(path))
        solids = imported.solids().vals()
    except Exception as exc:
        return {"ok": False, "checks": {}, "errors": [f"STEP re-import failed: {exc}"]}

    checks["solids"] = len(solids)
    if len(solids) != len(PART_ORDER):
        errors.append(f"Re-imported STEP has {len(solids)} solids, expected {len(PART_ORDER)}")
        return {"ok": False, "checks": checks, "errors": errors}

    want = sorted(parts[n].Volume() for n in PART_ORDER)
    got = sorted(s.Volume() for s in solids)
    checks["volumes"] = got
    for w, g in zip(want, got):
        if abs(g - w) / w > config.FRAME_VOLUME_REL_TOLERANCE:
            errors.append(f"Re-imported volume {g:.3f} vs expected {w:.3f}")
    if not all(s.isValid() for s in solids):
        errors.append("A re-imported solid is not valid")

    text = path.read_text(errors="ignore")
    missing = [n for n in PART_ORDER if n not in text]
    checks["names_missing"] = missing
    if missing:
        errors.append("Part names missing in STEP file: " + ", ".join(missing))

    xs, ys, zs = [], [], []
    for s in solids:
        bb = s.BoundingBox()
        xs += [bb.xmin, bb.xmax]
        ys += [bb.ymin, bb.ymax]
        zs += [bb.zmin, bb.zmax]
    dims = (max(xs) - min(xs), max(ys) - min(ys))
    checks["overall_xy"] = dims
    tol = config.FRAME_BBOX_TOLERANCE
    if abs(dims[0] - width) > tol or abs(dims[1] - height) > tol:
        errors.append(f"Overall size {dims[0]:.3f} x {dims[1]:.3f} vs {width} x {height}")

    return {"ok": not errors, "checks": checks, "errors": errors}


def generate_frame_step(width=config.DEFAULT_FRAME_WIDTH, height=config.DEFAULT_FRAME_HEIGHT,
                        out_path=None, sections_dir=None):
    if out_path is None:
        out_path = config.OUTPUT_DIR / config.FRAME_OUTPUT_NAME.format(w=int(width), h=int(height))
    out_path = Path(out_path)

    try:
        parts, report = build_frame(width, height, sections_dir=sections_dir)
    except FrameBuildError as exc:
        raise FrameGenerationError(f"Build error: {exc}", exc.report)

    report["step"] = str(out_path)

    overlaps, errors = _check_interference(parts, report)
    report["overlaps"] = overlaps
    if errors:
        raise FrameGenerationError("Frame fit check failed: " + "; ".join(errors), report)

    try:
        _export(parts, out_path)
    except Exception as exc:
        raise FrameGenerationError(f"STEP export failed: {exc}", report)

    file_report = _validate_step(out_path, parts, width, height)
    report["step_validation"] = file_report
    if not file_report["ok"]:
        out_path.unlink(missing_ok=True)
        raise FrameGenerationError("STEP re-import check failed: " + "; ".join(file_report["errors"]), report)

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
