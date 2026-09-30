"""Stage 5: automatic validation run on every export."""
from pathlib import Path

import cadquery as cq

from . import config

VOLUME_REL_TOL = getattr(config, "FRAME_VOLUME_REL_TOLERANCE", 5e-3)
BBOX_TOL = getattr(config, "FRAME_BBOX_TOLERANCE", 5e-3)
OVERLAP_REL_TOL = getattr(config, "WINDOW_OVERLAP_REL_TOLERANCE", 1e-3)
OVERLAP_ABS_TOL = 1e-6


class ValidationError(Exception):
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


def check_parts(parts, width, height):
    """Each part: valid solid, positive volume, one shell, inside the frame bounds."""
    errors = []
    info = {}
    for name, solid in parts.items():
        entry = {}
        entry["solids"] = len(solid.Solids())
        if entry["solids"] != 1:
            errors.append(f"{name}: expected 1 solid, found {entry['solids']}")

        entry["valid"] = bool(solid.isValid())
        if not entry["valid"]:
            errors.append(f"{name}: solid failed the OpenCASCADE validity check")

        entry["volume"] = solid.Volume()
        if entry["volume"] <= 0:
            errors.append(f"{name}: volume is zero or negative ({entry['volume']:.6f})")

        entry["shells"] = len(solid.Shells())
        if entry["shells"] != 1:
            errors.append(f"{name}: expected 1 shell, found {entry['shells']}")

        bb = solid.BoundingBox()
        entry["bbox"] = {"x": [bb.xmin, bb.xmax], "y": [bb.ymin, bb.ymax], "z": [bb.zmin, bb.zmax]}
        if (bb.xmin < -BBOX_TOL or bb.ymin < -BBOX_TOL
                or bb.xmax > width + BBOX_TOL or bb.ymax > height + BBOX_TOL):
            errors.append(
                f"{name}: outside frame bounds "
                f"(x {bb.xmin:.3f}..{bb.xmax:.3f}, y {bb.ymin:.3f}..{bb.ymax:.3f})")
        if bb.zmin < -BBOX_TOL:
            errors.append(f"{name}: extends in front of the front face (zmin = {bb.zmin:.3f})")
        info[name] = entry
    return info, errors


def check_overlaps(parts):
    """No two members may share volume; touching faces are allowed."""
    names = list(parts)
    overlaps = {}
    errors = []
    warnings = []
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
                warnings.append(f"Overlap check skipped for {key}: {exc}")
                continue
            if overlap > OVERLAP_ABS_TOL:
                overlaps[key] = overlap
            smaller = min(parts[a].Volume(), parts[b].Volume())
            if smaller > 0 and overlap > smaller * OVERLAP_REL_TOL:
                errors.append(f"{key} overlap {overlap:.3f} mm3")
    return overlaps, errors, checked, warnings


def check_overall_bbox(solids, width, height):
    """Combined X-Y extent of all members must equal the requested frame size."""
    errors = []
    boxes = [s.BoundingBox() for s in solids]
    if not boxes:
        return {}, ["No solids to measure"]
    xmin = min(b.xmin for b in boxes)
    xmax = max(b.xmax for b in boxes)
    ymin = min(b.ymin for b in boxes)
    ymax = max(b.ymax for b in boxes)
    dims = (xmax - xmin, ymax - ymin)
    checks = {"overall_xy": dims, "origin_xy": (xmin, ymin), "expected_xy": (width, height)}
    if abs(dims[0] - width) > BBOX_TOL or abs(dims[1] - height) > BBOX_TOL:
        errors.append(f"Overall size {dims[0]:.3f} x {dims[1]:.3f} vs {width} x {height}")
    if abs(xmin) > BBOX_TOL or abs(ymin) > BBOX_TOL:
        errors.append(f"Frame origin not at outer corner (xmin = {xmin:.3f}, ymin = {ymin:.3f})")
    return checks, errors


def validate_before_export(parts, width, height):
    """Checks on the in-memory solids, run before the STEP file is written."""
    part_info, part_errors = check_parts(parts, width, height)
    overlaps, overlap_errors, checked, warnings = check_overlaps(parts)
    overall, overall_errors = check_overall_bbox(list(parts.values()), width, height)
    errors = part_errors + overlap_errors + overall_errors
    return {
        "ok": not errors,
        "parts": part_info,
        "overlaps": overlaps,
        "pairs_checked": checked,
        "overall": overall,
        "warnings": warnings,
        "errors": errors,
    }


def _bbox_dims(solid):
    bb = solid.BoundingBox()
    return (bb.xlen, bb.ylen, bb.zlen)


def validate_step_file(path, parts, width, height):
    """Re-import the written STEP file and repeat the checks on what was actually saved."""
    path = Path(path)
    errors = []
    checks = {}

    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "checks": checks, "errors": [f"STEP file missing or empty: {path}"]}

    try:
        imported = cq.importers.importStep(str(path))
        solids = imported.solids().vals()
    except Exception as exc:
        return {"ok": False, "checks": checks, "errors": [f"STEP re-import failed: {exc}"]}

    checks["solids"] = len(solids)
    checks["expected_solids"] = len(parts)
    if len(solids) != len(parts):
        errors.append(f"Re-imported STEP has {len(solids)} solids, expected {len(parts)}")
        return {"ok": False, "checks": checks, "errors": errors}

    want = sorted(parts.values(), key=lambda s: s.Volume())
    got = sorted(solids, key=lambda s: s.Volume())
    for w, g in zip(want, got):
        wv, gv = w.Volume(), g.Volume()
        if wv <= 0 or gv <= 0:
            errors.append(f"Non-positive volume after re-import (expected {wv:.3f}, got {gv:.3f})")
            continue
        if abs(gv - wv) / wv > VOLUME_REL_TOL:
            errors.append(f"Re-imported volume {gv:.3f} vs expected {wv:.3f}")
        for axis, a, b in zip("XYZ", _bbox_dims(w), _bbox_dims(g)):
            if abs(a - b) > BBOX_TOL:
                errors.append(f"Re-imported bbox {axis} {b:.3f} vs expected {a:.3f}")
    checks["volumes"] = [s.Volume() for s in got]

    if not all(s.isValid() for s in solids):
        errors.append("A re-imported solid is not valid")

    text = path.read_text(errors="ignore")
    missing = [n for n in parts if n not in text]
    checks["names_missing"] = missing
    if missing:
        errors.append("Part names missing in STEP file: " + ", ".join(missing))

    overall, overall_errors = check_overall_bbox(solids, width, height)
    checks.update(overall)
    errors += overall_errors

    indexed = {f"Solid_{i + 1}": s for i, s in enumerate(solids)}
    overlaps, overlap_errors, checked, warnings = check_overlaps(indexed)
    checks["overlaps"] = overlaps
    checks["pairs_checked"] = checked
    checks["warnings"] = warnings
    errors += [f"Re-imported {e}" for e in overlap_errors]

    return {"ok": not errors, "checks": checks, "errors": errors}


def require_ok(report, label):
    if not report.get("ok"):
        raise ValidationError(f"{label}: " + "; ".join(report.get("errors", [])), report)
    return report
