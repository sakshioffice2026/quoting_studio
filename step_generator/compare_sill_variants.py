"""Write one window STEP per sill orientation so they can be compared in a CAD viewer.

Run from the project root:
    python -m step_generator.compare_sill_variants
    python -m step_generator.compare_sill_variants --width 1000 --height 1200

Variants (only the Sill differs):
    A_current        depth = drawn X   sill z 0..165, nosing at the front (today's build)
    B_nosing_front   as A, moved back so its rear face lines up with head/jambs (z -75..90)
    C_depth_flipped  depth = 165 - drawn X   sill z 0..165, frame part aligned with head/jambs
    D_upside_down    across flipped (outer edge = drawn Y max), depth = drawn X
"""
import argparse
import sys
from pathlib import Path

import cadquery as cq

from . import config
from .frame_builder import FrameBuildError
from .window_builder import build_window

VARIANTS = (
    ("A_current", "swap", False),
    ("B_nosing_front", "swap", True),
    ("C_depth_flipped", "rot270", False),
    ("D_upside_down", "rot90", False),
)


def _export(parts, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="Window")
    for name, solid in parts.items():
        assembly.add(solid, name=name)
    assembly.save(str(path), exportType="STEP")


def _z_range(solid):
    bb = solid.BoundingBox()
    return bb.zmin, bb.zmax


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare sill orientations in the window STEP")
    parser.add_argument("--width", type=float, default=config.DEFAULT_FRAME_WIDTH)
    parser.add_argument("--height", type=float, default=config.DEFAULT_FRAME_HEIGHT)
    args = parser.parse_args(argv)

    out_dir = config.OUTPUT_DIR / "sill_variants"
    saved_mode = config.SECTION_ORIENTATION.get("Sill")
    status = 0

    try:
        for tag, mode, align_back in VARIANTS:
            config.SECTION_ORIENTATION["Sill"] = mode
            try:
                parts, report = build_window(args.width, args.height)
            except FrameBuildError as exc:
                print(f"{tag}: FAILED - {exc}")
                status = 1
                continue

            if align_back:
                shift = report["depth"]["Jamb_Left"] - report["depth"]["Sill"]
                parts["Sill"] = parts["Sill"].translate(cq.Vector(0.0, 0.0, shift))

            path = out_dir / f"window_sill_{tag}.step"
            _export(parts, path)

            head_z = _z_range(parts["Head"])
            jamb_z = _z_range(parts["Jamb_Left"])
            sill_z = _z_range(parts["Sill"])
            print(f"{tag}: {path}")
            print(f"    Head  z {head_z[0]:8.1f} .. {head_z[1]:.1f}")
            print(f"    Jamb  z {jamb_z[0]:8.1f} .. {jamb_z[1]:.1f}")
            print(f"    Sill  z {sill_z[0]:8.1f} .. {sill_z[1]:.1f}")
    finally:
        config.SECTION_ORIENTATION["Sill"] = saved_mode

    return status


if __name__ == "__main__":
    sys.exit(main())
