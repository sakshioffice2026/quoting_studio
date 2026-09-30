"""Stage 3: complete window -> one validated STEP with named parts.

Run from the project root:
    python -m step_generator.generate_window --width 1200 --height 1400
"""
import argparse
import json
import sys
from pathlib import Path

import cadquery as cq

from . import config
from .frame_builder import FrameBuildError
from .window_builder import build_window


class WindowGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _boxes_touch(a, b, tol=1e-6):
    A, B = a.BoundingBox(), b.BoundingBox()
    return not (
        A.xmax < B.xmin - tol or B.xmax < A.xmin - tol
        or A.ymax < B.ymin - tol or B.ymax < A.ymin - tol
        or A.zmax < B.zmin - tol or B.zmax < A.zmin - tol
    )


def _check_interference(parts, report):
    """No two members may overlap; contact faces (zero volume) are fine."""
    names = list(parts)
    overlaps = {}
    errors = []
    checked = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not _boxes_touch(parts[a], parts[b]):
                continue
            checked += 1
            key = f"{a}+{b}"
            try:
                common = parts[a].intersect(parts[b])
                overlap = sum(s.Volume() for s in common.Solids())
            except Exception as exc:
                report["warnings"].append(f"Interference check skipped for {key}: {exc}")
                continue
            if overlap > 1e-6:
                overlaps[key] = overlap
            smaller = min(parts[a].Volume(), parts[b].Volume())
            if overlap > smaller * config.WINDOW_OVERLAP_REL_TOLERANCE:
                errors.append(f"{key} overlap {overlap:.3f} mm3")
    return overlaps, errors, checked


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


def _validate_step(path, parts, width, height):
    errors = []
    checks = {}

    try:
        imported = cq.importers.importStep(str(path))
        solids = imported.solids().vals()
    except Exception as exc:
        return {"ok": False, "checks": {}, "errors": [f"STEP re-import failed: {exc}"]}

    checks["solids"] = len(solids)
    checks["expected_solids"] = len(parts)
    if len(solids) != len(parts):
        errors.append(f"Re-imported STEP has {len(solids)} solids, expected {len(parts)}")
        return {"ok": False, "checks": checks, "errors": errors}

    want = sorted(p.Volume() for p in parts.values())
    got = sorted(s.Volume() for s in solids)
    for w, g in zip(want, got):
        if w <= 0 or abs(g - w) / w > config.FRAME_VOLUME_REL_TOLERANCE:
            errors.append(f"Re-imported volume {g:.3f} vs expected {w:.3f}")
    if not all(s.isValid() for s in solids):
        errors.append("A re-imported solid is not valid")

    text = path.read_text(errors="ignore")
    missing = [n for n in parts if n not in text]
    checks["names_missing"] = missing
    if missing:
        errors.append("Part names missing in STEP file: " + ", ".join(missing))

    xs, ys = [], []
    for s in solids:
        bb = s.BoundingBox()
        xs += [bb.xmin, bb.xmax]
        ys += [bb.ymin, bb.ymax]
    dims = (max(xs) - min(xs), max(ys) - min(ys))
    checks["overall_xy"] = dims
    tol = config.FRAME_BBOX_TOLERANCE
    if abs(dims[0] - width) > tol or abs(dims[1] - height) > tol:
        errors.append(f"Overall size {dims[0]:.3f} x {dims[1]:.3f} vs {width} x {height}")

    return {"ok": not errors, "checks": checks, "errors": errors}


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

    overlaps, errors, checked = _check_interference(parts, report)
    report["overlaps"] = overlaps
    report["interference_pairs_checked"] = checked
    if errors:
        raise WindowGenerationError("Window fit check failed: " + "; ".join(errors), report)

    try:
        _export(parts, out_path)
    except Exception as exc:
        raise WindowGenerationError(f"STEP export failed: {exc}", report)

    file_report = _validate_step(out_path, parts, width, height)
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
