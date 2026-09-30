"""Independent checks for a generated solid and for the exported STEP file."""
import cadquery as cq

from . import config


def validate_solid(solid, profile, length):
    """Return (solid, report). The solid is healed once if OCC reports it invalid."""
    errors = []
    checks = {}

    checks["valid_before_heal"] = bool(solid.isValid())
    if not checks["valid_before_heal"]:
        try:
            healed = solid.fix()
            solids = healed.Solids()
            if len(solids) == 1:
                solid = solids[0]
            checks["healed"] = True
        except Exception as exc:
            errors.append(f"Heal failed: {exc}")

    checks["valid"] = bool(solid.isValid())
    if not checks["valid"]:
        errors.append("Solid failed the OpenCASCADE validity check")

    volume = solid.Volume()
    expected = profile.area * length
    checks["volume"] = volume
    checks["expected_volume"] = expected
    if volume <= 0:
        errors.append("Solid volume is zero or negative")
    elif abs(volume - expected) / expected > config.VOLUME_REL_TOLERANCE:
        errors.append(
            f"Volume {volume:.3f} differs from expected {expected:.3f} "
            f"(profile area x length)"
        )

    checks["shells"] = len(solid.Shells())
    if checks["shells"] != 1:
        errors.append(f"Expected 1 shell, found {checks['shells']}")

    bb = solid.BoundingBox()
    dims = (bb.xlen, bb.ylen, bb.zlen)
    expected_dims = (profile.width, profile.height, length)
    checks["bbox"] = dims
    checks["expected_bbox"] = expected_dims
    for name, got, want in zip("XYZ", dims, expected_dims):
        if abs(got - want) > config.BBOX_TOLERANCE:
            errors.append(f"Bounding box {name}: {got:.4f} vs expected {want:.4f}")

    if profile.normalized:
        for name, v in (("X", bb.xmin), ("Y", bb.ymin), ("Z", bb.zmin)):
            if abs(v) > config.BBOX_TOLERANCE:
                errors.append(f"Origin not at bounding-box corner ({name}min = {v:.4f})")

    return solid, {"ok": not errors, "checks": checks, "errors": errors}


def validate_step_file(path, expected_volume, expected_dims):
    """Re-import the STEP file and compare volume, solid count and size."""
    errors = []
    checks = {}
    try:
        imported = cq.importers.importStep(str(path))
        solids = imported.solids().vals()
    except Exception as exc:
        return {"ok": False, "checks": {}, "errors": [f"STEP re-import failed: {exc}"]}

    checks["solids"] = len(solids)
    if len(solids) != 1:
        errors.append(f"Re-imported STEP has {len(solids)} solids, expected 1")
        return {"ok": False, "checks": checks, "errors": errors}

    solid = solids[0]
    volume = solid.Volume()
    checks["volume"] = volume
    if abs(volume - expected_volume) / expected_volume > config.VOLUME_REL_TOLERANCE:
        errors.append(f"Re-imported volume {volume:.3f} vs expected {expected_volume:.3f}")

    if not solid.isValid():
        errors.append("Re-imported solid is not valid")

    bb = solid.BoundingBox()
    dims = (bb.xlen, bb.ylen, bb.zlen)
    checks["bbox"] = dims
    for name, got, want in zip("XYZ", dims, expected_dims):
        if abs(got - want) > config.BBOX_TOLERANCE:
            errors.append(f"Re-imported bounding box {name}: {got:.4f} vs {want:.4f}")

    return {"ok": not errors, "checks": checks, "errors": errors}
