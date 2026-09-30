"""Stage 1: one section DXF -> one validated STEP solid.

Run from the project root:
    python -m step_generator.generate_section app/cad_sections/cad_sections/jamb.dxf --length 1000
"""
import argparse
import json
import re
import sys
from pathlib import Path

from . import config
from .dxf_profile import ProfileError, load_profile
from .exporter import export_step
from .solid_builder import SolidBuildError, build_solid
from .validator import validate_solid, validate_step_file


class StepGenerationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "Section"


def generate_section_step(dxf_path, length=config.DEFAULT_LENGTH, out_path=None,
                          part_name=None, normalize_origin=True, layers=None):
    dxf_path = Path(dxf_path)
    part_name = part_name or _safe_name(dxf_path.stem)
    if out_path is None:
        out_path = config.OUTPUT_DIR / f"{_safe_name(dxf_path.stem)}_{int(length)}mm.step"
    out_path = Path(out_path)

    report = {"dxf": str(dxf_path), "part": part_name, "length": length, "step": str(out_path)}

    try:
        profile = load_profile(dxf_path, normalize_origin=normalize_origin, layers=layers)
    except ProfileError as exc:
        raise StepGenerationError(f"Profile error: {exc}", report)

    report["profile"] = {
        "width": profile.width,
        "height": profile.height,
        "area": profile.area,
        "holes": len(profile.holes),
        "skipped_entities": profile.skipped,
        "warnings": profile.warnings,
    }

    try:
        solid = build_solid(profile, length)
    except SolidBuildError as exc:
        raise StepGenerationError(f"Build error: {exc}", report)

    solid, solid_report = validate_solid(solid, profile, length)
    report["solid_validation"] = solid_report
    if not solid_report["ok"]:
        raise StepGenerationError("Solid validation failed: " + "; ".join(solid_report["errors"]), report)

    export_step(solid, out_path, part_name)

    file_report = validate_step_file(
        out_path,
        expected_volume=solid_report["checks"]["volume"],
        expected_dims=solid_report["checks"]["expected_bbox"],
    )
    report["step_validation"] = file_report
    if not file_report["ok"]:
        out_path.unlink(missing_ok=True)
        raise StepGenerationError("STEP re-import check failed: " + "; ".join(file_report["errors"]), report)

    report["ok"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a validated STEP file from a section DXF")
    parser.add_argument("dxf", help="Path to the section DXF")
    parser.add_argument("--length", type=float, default=config.DEFAULT_LENGTH, help="Extrusion length in mm")
    parser.add_argument("--out", default=None, help="Output .step path")
    parser.add_argument("--name", default=None, help="Part name stored in the STEP file")
    parser.add_argument("--no-normalize", action="store_true", help="Keep DXF coordinates (do not move to origin)")
    parser.add_argument("--layers", nargs="*", default=None, help="Only read these DXF layers")
    args = parser.parse_args(argv)

    try:
        report = generate_section_step(
            args.dxf,
            length=args.length,
            out_path=args.out,
            part_name=args.name,
            normalize_origin=not args.no_normalize,
            layers=set(args.layers) if args.layers else None,
        )
    except StepGenerationError as exc:
        print(json.dumps(exc.report, indent=2, default=str))
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, default=str))
    print(f"OK: {report['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
