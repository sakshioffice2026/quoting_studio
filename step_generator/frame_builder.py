"""Stage 2: build the four frame members (butt or mitre joints) from section DXFs.

Joint type is FRAME_JOINT below: "butt" = Head and Sill full width with the jambs
running between them; "mitre" = diagonal corners.

Frame coordinates (mm):
    X = frame width, Y = frame height, Z = wall depth (0 = front face).
Each section profile (after origin normalisation) uses
    profile X = across (measured inward from the outer edge)
    profile Y = depth  (along frame +Z)
Every member is extruded long, then trimmed by its mitre envelope: a
trapezoid in the X-Y plane whose corner lines run from the outer corner to
the inner corner, so members with different widths still meet exactly.

Butt joint gap fill: when the inner face of the Head or Sill is stepped (its
across is smaller than the full section width at some depths), the jambs would
end square and leave a gap. Each jamb is therefore extended into the Head and
Sill zone and the solid outline of the Head / Sill is cut away from it, so the
jamb meets the stepped face exactly and never overlaps the Head or Sill.
"""
from pathlib import Path

import cadquery as cq

from . import config
from .dxf_profile import Profile, ProfileError, load_profile
from .profile_transform import orient_profile
from .solid_builder import SolidBuildError, build_solid


class FrameBuildError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


PART_ORDER = ("Head", "Sill", "Jamb_Left", "Jamb_Right")
JAMBS = ("Jamb_Left", "Jamb_Right")

# Corner joint: "butt" (jambs between head and sill, as in the app) or "mitre".
FRAME_JOINT = getattr(config, "FRAME_JOINT", "butt")

# Jamb gap fill (butt joint only).
FILL_MIN_GAP = 0.05      # mm: smaller gaps are ignored
FILL_MARGIN = 1.0        # mm: extra reach into the Head / Sill (removed by the cut)
FILL_DEPTH_SAMPLES = 100
FILL_DEPTH_EPS = 0.01    # mm: samples stay this far inside the depth range (float safety)
FILL_FRAGMENT_REL = 0.02  # loose fragments above this share of the jamb volume skip the fill

# Orientation chosen by section FILE NAME (overrides SECTION_ORIENTATION per part).
# sill.dxf: rot270 = a true rotation (never mirrored). Depth = drawn width - drawn X,
# so the sloped nosing points to +Z and the frame-fitting part lines up with the
# head/jambs at z 0..90. Other section files (e.g. the door sill) are not affected.
_DEFAULT_ORIENTATION_BY_FILE = {"sill.dxf": "rot270"}


def _orientation_for(name, fname):
    by_file = getattr(config, "SECTION_ORIENTATION_BY_FILE", _DEFAULT_ORIENTATION_BY_FILE)
    key = Path(str(fname)).name.lower()
    if key in by_file:
        return by_file[key]
    return config.SECTION_ORIENTATION.get(name, "as_drawn")


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


def _envelopes(width, height, a, joint=None):
    """Envelope polygons (X-Y plane) that tile the frame ring.

    butt  : Head and Sill run the full width; the jambs run between the top of the
            sill and the underside of the head (square cuts).
    mitre : diagonal corner lines from the outer corner to the inner corner.
    """
    joint = joint or FRAME_JOINT
    aj_l, aj_r = a["Jamb_Left"], a["Jamb_Right"]
    a_h, a_s = a["Head"], a["Sill"]
    if joint == "butt":
        return {
            "Sill": [(0.0, 0.0), (width, 0.0), (width, a_s), (0.0, a_s)],
            "Head": [(0.0, height - a_h), (width, height - a_h), (width, height), (0.0, height)],
            "Jamb_Left": [(0.0, a_s), (aj_l, a_s), (aj_l, height - a_h), (0.0, height - a_h)],
            "Jamb_Right": [(width - aj_r, a_s), (width, a_s), (width, height - a_h), (width - aj_r, height - a_h)],
        }
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


def _prism(polygon, z_top):
    """Prism over an X-Y polygon, spanning z = -1 .. z_top."""
    return (
        cq.Workplane("XY", origin=(0, 0, -1.0))
        .polyline(polygon).close()
        .extrude(z_top + 1.0)
        .val()
    )


def _outline_only(profile):
    """Same profile with its holes filled in (solid outline)."""
    return Profile(
        outer=profile.outer,
        holes=[],
        width=profile.width,
        height=profile.height,
        normalized=profile.normalized,
        skipped=profile.skipped,
        warnings=profile.warnings,
    )


def _min_reach(profile, depth_limit):
    """Smallest inner reach of the outline over depth 0..depth_limit.

    At every depth the reach is the largest across the outline has there; the
    result is the smallest of those values. A value below the section width
    means the inner face is stepped and a square-ended jamb would leave a gap.
    """
    pts = profile.outer.points()
    n = len(pts)
    if n < 3:
        return None
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]

    lo = FILL_DEPTH_EPS
    hi = depth_limit - FILL_DEPTH_EPS
    if hi <= lo:
        return None

    def clamp(z):
        return min(max(z, lo), hi)

    depths = {lo + (hi - lo) * i / FILL_DEPTH_SAMPLES for i in range(FILL_DEPTH_SAMPLES + 1)}
    for p in pts:
        if -FILL_DEPTH_EPS <= p[1] <= depth_limit + FILL_DEPTH_EPS:
            depths.add(clamp(p[1] - FILL_DEPTH_EPS))
            depths.add(clamp(p[1] + FILL_DEPTH_EPS))

    lowest = None
    for z in sorted(depths):
        top = None
        for (x0, y0), (x1, y1) in edges:
            if (y0 - z) * (y1 - z) > 0.0:
                continue
            if y0 == y1:
                candidates = (x0, x1)
            else:
                t = (z - y0) / (y1 - y0)
                candidates = (x0 + t * (x1 - x0),)
            for x in candidates:
                top = x if top is None else max(top, x)
        if top is None:
            continue
        lowest = top if lowest is None else min(lowest, top)
    return lowest


def _keep_main_solid(shape, name, report):
    """Return the main solid of a cut result; drop tiny loose fragments."""
    solids = shape.Solids()
    if not solids:
        raise FrameBuildError(f"{name}: gap fill produced no solid")
    if len(solids) == 1:
        return solids[0]
    solids = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    main = solids[0]
    loose = sum(s.Volume() for s in solids[1:])
    if loose > main.Volume() * FILL_FRAGMENT_REL:
        raise FrameBuildError(
            f"{name}: gap fill left {len(solids) - 1} loose pieces ({loose:.1f} mm3)")
    report["warnings"].append(
        f"{name}: dropped {len(solids) - 1} tiny loose fragment(s) from the gap fill")
    return main


def _fill_lengths(profiles, across):
    """How far each jamb must reach into the Sill / Head zone to close stepped faces."""
    depth_limit = min(profiles[name].height for name in JAMBS)
    lengths = {"Sill": 0.0, "Head": 0.0}
    for name in lengths:
        reach = _min_reach(profiles[name], depth_limit)
        if reach is None:
            continue
        gap = across[name] - reach
        if gap > FILL_MIN_GAP:
            lengths[name] = min(across[name], gap + FILL_MARGIN)
    return lengths


def _jamb_fill_polygon(name, width, height, a, fill):
    aj_l, aj_r = a["Jamb_Left"], a["Jamb_Right"]
    lo = a["Sill"] - fill["Sill"]
    hi = height - a["Head"] + fill["Head"]
    if name == "Jamb_Left":
        x0, x1 = 0.0, aj_l
    else:
        x0, x1 = width - aj_r, width
    return [(x0, lo), (x1, lo), (x1, hi), (x0, hi)]


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
        try:
            profiles[name] = orient_profile(cache[fname], _orientation_for(name, fname))
        except ValueError as exc:
            raise FrameBuildError(f"{name}: {exc}", report)

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

    fill = {"Sill": 0.0, "Head": 0.0}
    if FRAME_JOINT == "butt":
        try:
            fill = _fill_lengths(profiles, across)
        except Exception as exc:
            report["warnings"].append(f"Jamb gap fill skipped: {exc}")
    report["jamb_fill"] = dict(fill)

    outlines = {}   # solid outlines of Head / Sill in frame coordinates (cut tools)

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
            envelope = _prism(envelopes[name], z_top)
            cut = placed.intersect(envelope)
        except Exception as exc:
            raise FrameBuildError(f"{name}: mitre cut failed: {exc}", report)

        if name in fill and fill[name] > 0.0:
            try:
                outline = _outline_only(profile)
                placed_outline = _place(build_solid(outline, length), outline, name, spec, length)
                outlines[name] = placed_outline.intersect(envelope)
            except Exception as exc:
                report["warnings"].append(f"{name}: outline for jamb gap fill failed: {exc}")

        if name in JAMBS and outlines:
            try:
                fill_envelope = _prism(_jamb_fill_polygon(name, width, height, across, fill), z_top)
                candidate = placed.intersect(fill_envelope)
                for tool in outlines.values():
                    candidate = candidate.cut(tool)
                cut = _keep_main_solid(candidate, name, report)
            except Exception as exc:
                report["warnings"].append(f"{name}: jamb gap fill skipped: {exc}")

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
        expected_span = spec["outer_length"]
        max_span = expected_span
        if FRAME_JOINT == "butt" and name in JAMBS:
            expected_span = height - across["Head"] - across["Sill"]
            max_span = expected_span + fill["Sill"] + fill["Head"]
        if span < expected_span - 0.05 or span > max_span + 0.05:
            report["warnings"].append(
                f"{name}: length {span:.3f} differs from {expected_span:.3f} "
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
