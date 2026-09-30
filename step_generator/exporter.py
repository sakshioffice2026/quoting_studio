"""Write a solid to a STEP file as a named part."""
from pathlib import Path

import cadquery as cq


def export_step(solid, path, part_name):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        assembly = cq.Assembly(name=part_name)
        assembly.add(solid, name=part_name)
        assembly.save(str(path), exportType="STEP")
    except Exception:
        # Fallback: plain single-shape export (part name is not stored).
        cq.exporters.export(cq.Workplane("XY").newObject([solid]), str(path), exportType="STEP")

    if not path.is_file() or path.stat().st_size == 0:
        raise IOError(f"STEP export produced no file: {path}")
    return path
