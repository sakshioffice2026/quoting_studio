"""Stage 3 (batch): every section DXF -> one validated STEP, one origin convention.

Each section is normalised so the profile bounding-box corner sits at (0, 0):
    profile X = across, profile Y = depth, extrusion = +Z (length).
generate_section_step verifies that convention on every solid it exports.

Run from the project root:
    python -m step_generator.generate_all_sections
    python -m step_generator.generate_all_sections --length 1000 --out step_generator/output/sections
"""
import argparse
import json
import re
import sys
from pathlib import Path

from . import config
from .generate_section import StepGenerationError, generate_section_steps


def find_section_dxfs(directories=None):
    """All .dxf files (recursive) under the section folders, backups excluded."""
    directories = [Path(d) for d in (directories or config.ALL_SECTION_DIRS)]
    found = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".dxf":
                continue
            if path.name.lower().endswith(config.SECTION_SKIP_SUFFIXES):
                continue
            found.append((directory, path))
    return found


def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "Section"


def _unique_name(base_dir, path, used):
    relative = path.relative_to(base_dir).with_suffix("")
    name = _safe_name("_".join(relative.parts))
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{name}_{n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def generate_all_sections(length=config.SECTION_EXPORT_LENGTH, out_dir=None, directories=None):
    out_dir = Path(out_dir) if out_dir else config.OUTPUT_DIR / config.SECTIONS_OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = find_section_dxfs(directories)
    results = []
    used = set()

    for base_dir, dxf in entries:
        name = _unique_name(base_dir, dxf, used)
        row = {"dxf": str(dxf), "name": name, "ok": False}
        try:
            reports = generate_section_steps(
                dxf, length=length, out_dir=out_dir, part_name=name, file_stem=name)
            first = reports[0]["profile"]
            row.update({
                "ok": True,
                "shapes": len(reports),
                "steps": [r["step"] for r in reports],
                "shape_sizes": [[r["profile"]["width"], r["profile"]["height"]] for r in reports],
                "across": first["width"],
                "depth": first["height"],
                "area": first["area"],
                "holes": first["holes"],
                "skipped_entities": first["skipped_entities"],
                "warnings": first["warnings"],
                "volume": sum(r["solid_validation"]["checks"]["volume"] for r in reports),
            })
        except StepGenerationError as exc:
            row["error"] = str(exc)
            row["warnings"] = exc.report.get("profile", {}).get("warnings", [])
        except Exception as exc:  # keep the batch going; the failure is reported
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)

    failed = [r for r in results if not r["ok"]]
    return {
        "length": length,
        "out_dir": str(out_dir),
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "with_warnings": sum(1 for r in results if r.get("warnings")),
        "sections": results,
        "ok": bool(results) and not failed,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate validated STEP files for every section DXF")
    parser.add_argument("--length", type=float, default=config.SECTION_EXPORT_LENGTH, help="Extrusion length in mm")
    parser.add_argument("--out", default=None, help="Output folder for the STEP files")
    parser.add_argument("--dirs", nargs="*", default=None, help="Folders to scan instead of the defaults")
    args = parser.parse_args(argv)

    summary = generate_all_sections(length=args.length, out_dir=args.out, directories=args.dirs)

    report_path = Path(summary["out_dir"]) / config.SECTIONS_REPORT_NAME
    report_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    for row in summary["sections"]:
        if row["ok"]:
            flag = "WARN" if row.get("warnings") else "OK  "
            shapes = f"  [{row['shapes']} shapes]" if row["shapes"] > 1 else ""
            print(f"{flag} {row['name']}  {row['across']:.2f} x {row['depth']:.2f} mm{shapes}")
        else:
            print(f"FAIL {row['name']}: {row['error']}")

    print(
        f"\n{summary['passed']}/{summary['total']} passed, "
        f"{summary['failed']} failed, {summary['with_warnings']} with warnings"
    )
    print(f"Report: {report_path}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
