"""Stage 2: build the four mitred frame members from section DXFs.

Frame coordinates (mm):
    X = frame width, Y = frame height, Z = wall depth (0 = front face).
Each section profile (after origin normalisation) uses
    profile X = across (measured inward from the outer edge)
    profile Y = depth  (along frame +Z)
Every member is extruded long, then trimmed by its mitre envelope: a
trapezoid in the X-Y plane whose corner lines run from the outer corner to
the inner corner, so members with different widths still meet exactly.
"""
from pathlib import Path

import cadquery as cq

from . import config
from .dxf_profile import ProfileError, load_profile
from .solid_builder import SolidBuildError, build_solid


class FrameBuildError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


PART_ORDER = ("Head", "Sill", "Jamb_Left", "Jamb_Right")


def _member_layout(width, height):
    """Per part: base origin, across direction, length direction, outer length.

    depth direction = length x across = +Z for every member.
    """
    return {
        "Sill": {
            "origin": (0.0, 0.0, 0.0),
            "across": (0.0, 1.0, 0.0),
            "length": (1.0, 0.0, 0.0),
            "outer_length": width,
        },
        "Head": {
            "origin": (width, height, 0.0),
            "across": (0.0, -1.0, 0.0),
            "length": (-1.0, 0.0, 0.0),
            "outer_length": width,
        },
        "Jamb_Left": {
            "origin": (0.0, height, 0.0),
            "across": (1.0, 0.0, 0.0),
            "length": (0.0, -1.0, 0.0),
            "outer_length": height,
        },
        "Jamb_Right": {
            "origin": (width, 0.0, 0.0),
            "across": (-1.0, 0.0, 0.0),
            "length": (0.0, 1.0, 0.0),
            "outer_length": height,
        },
    }


def _envelopes(width, height, a):
    """Mitre envelope polygons (X-Y plane) that tile the frame ring."""
    aj_l, aj_r = a["Jamb_Left"], a["Jamb_Right"]
    a_h, a_s = a["Head"], a["Sill"]
    return {
        "Sill": [(0.0, 0.0), (width, 0.0), (width - aj_r, a_s), (aj_l, a_s)],
        "Head": [(0.0, height), (width, height), (width - aj_r, height - a_h), (aj_l, height - a_h)],
        "Jamb_Left": [(0.0, 0.0), (aj_l, a_s), (aj_l, height - a_h), (0.0, height)],
        "Jamb_Right": [(width, 0.0), (width, height), (width - aj_r, height - a_h), (width - aj_r, a_s)],
    }


def _add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k)


def _place(solid, profile, name, spec, length):
    """Apply flips, then move the +Z extrusion onto the member's plane."""
    if config.ACROSS_FLIP.get(name):
        solid = solid.mirror("YZ", (profile.width / 2.0, 0.0, 0.0))
    if config.DEPTH_FLIP.get(name):
        solid = solid.mirror("ZX", (0.0, profile.height / 2.0, 0.0))

    origin = _add(spec["origin"], spec["length"], -config.MITRE_OVERSIZE)
    plane = cq.Plane(origin=origin, xDir=spec["across"], normal=spec["length"])
    return solid.transformShape(plane.rG)


def _single_solid(shape, what):
    solids = shape.Solids()
    if len(solids) != 1:
        raise FrameBuildError(f"{what}: expected 1 solid after mitre cut, got {len(solids)}")
    return solids[0]


def build_frame(width=config.DEFAULT_FRAME_WIDTH, height=config.DEFAULT_FRAME_HEIGHT,
                sections_dir=None):
    """Return (parts, report). parts maps part name -> cadquery Solid."""
    sections_dir = Path(sections_dir) if sections_dir else config.SECTIONS_DIR
    report = {"width": width, "height": height, "parts": {}, "warnings": []}

    profiles = {}
    cache = {}
    for name in PART_ORDER:
        fname = config.FRAME_SECTION_FILES[name]
        if fname not in cache:
            path = sections_dir / fname
            if not path.is_file():
                raise FrameBuildError(f"Section DXF not found: {path}", report)
            try:
                cache[fname] = load_profile(path, normalize_origin=True)
            except ProfileError as exc:
                raise FrameBuildError(f"{fname}: {exc}", report)
            for warning in cache[fname].warnings:
                report["warnings"].append(f"{fname}: {warning}")
        profiles[name] = cache[fname]

    across = {n: profiles[n].width for n in PART_ORDER}
    depth = {n: profiles[n].height for n in PART_ORDER}
    report["across"] = across
    report["depth"] = depth

    if width <= across["Jamb_Left"] + across["Jamb_Right"]:
        raise FrameBuildError(
            f"Frame width {width} must exceed the two jamb widths "
            f"({across['Jamb_Left'] + across['Jamb_Right']:.2f})", report)
    if height <= across["Head"] + across["Sill"]:
        raise FrameBuildError(
            f"Frame height {height} must exceed head + sill widths "
            f"({across['Head'] + across['Sill']:.2f})", report)

    layout = _member_layout(width, height)
    envelopes = _envelopes(width, height, across)
    z_top = max(depth.values()) + 2.0

    parts = {}
    for name in PART_ORDER:
        spec = layout[name]
        profile = profiles[name]
        length = spec["outer_length"] + 2.0 * config.MITRE_OVERSIZE

        try:
            raw = build_solid(profile, length)
        except SolidBuildError as exc:
            raise FrameBuildError(f"{name}: {exc}", report)

        placed = _place(raw, profile, name, spec, length)

        try:
            envelope = (
                cq.Workplane("XY", origin=(0, 0, -1.0))
                .polyline(envelopes[name]).close()
                .extrude(z_top + 1.0)
                .val()
            )
            cut = placed.intersect(envelope)
        except Exception as exc:
            raise FrameBuildError(f"{name}: mitre cut failed: {exc}", report)

        solid = _single_solid(cut, name)
        if not solid.isValid():
            try:
                healed = solid.fix()
                solid = _single_solid(healed, name)
            except Exception as exc:
                raise FrameBuildError(f"{name}: invalid solid after mitre cut: {exc}", report)
            if not solid.isValid():
                raise FrameBuildError(f"{name}: solid is invalid after healing", report)

        bb = solid.BoundingBox()
        tol = config.FRAME_BBOX_TOLERANCE
        if bb.xmin < -tol or bb.ymin < -tol or bb.xmax > width + tol or bb.ymax > height + tol:
            raise FrameBuildError(
                f"{name}: outside frame bounds "
                f"(x {bb.xmin:.2f}..{bb.xmax:.2f}, y {bb.ymin:.2f}..{bb.ymax:.2f})", report)

        span = bb.xlen if name in ("Head", "Sill") else bb.ylen
        if abs(span - spec["outer_length"]) > 0.05:
            report["warnings"].append(
                f"{name}: outer length {span:.3f} differs from {spec['outer_length']:.3f} "
                f"(profile may not touch its outer edge)")

        if bb.zmin < -tol:
            report["warnings"].append(
                f"{name}: extends to z={bb.zmin:.2f}; check DEPTH_FLIP")

        parts[name] = solid
        report["parts"][name] = {
            "dxf": config.FRAME_SECTION_FILES[name],
            "across": across[name],
            "depth": depth[name],
            "volume": solid.Volume(),
            "bbox": {
                "x": [bb.xmin, bb.xmax],
                "y": [bb.ymin, bb.ymax],
                "z": [bb.zmin, bb.zmax],
            },
        }

    return parts, report
