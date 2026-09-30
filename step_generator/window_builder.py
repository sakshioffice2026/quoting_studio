"""Stage 3: build the complete window from section DXFs.

Frame coordinates (mm): X = width, Y = height, Z = wall depth (0 = front face).
Every section uses one convention: profile X = across, profile Y = depth (+Z),
extrusion = member length.

Parts:
    Head, Sill, Jamb_Left, Jamb_Right   mitred frame (Stage 2)
    Mullion                             vertical, square-cut between sill and head
    Transom_Left, Transom_Right         horizontal, square-cut between jamb and mullion
    Bead_<Row>_<Col>_<Side>             4 mitred beads inside each glazed opening

Gap fill: where the face a member butts against is stepped or chamfered, a
square-ended member leaves a gap. The Mullion and the Transoms are therefore
extended into the neighbouring member (only as far as the gap needs, and only
over the depth the neighbour really occupies) and the neighbour's solid outline
is cut away, so they meet exactly and never overlap.
"""
from pathlib import Path

import cadquery as cq

from . import config, frame_builder
from .dxf_profile import ProfileError, load_profile
from .frame_builder import FrameBuildError, _single_solid, build_frame
from .profile_transform import orient_profile
from .solid_builder import SolidBuildError, build_solid


class WindowBuildError(FrameBuildError):
    pass


SIDES = ("Bottom", "Top", "Left", "Right")

# Gap fill settings.
FILL_MIN_GAP = 0.05      # mm: smaller gaps are ignored
FILL_MARGIN = 1.0        # mm: extra reach into the neighbour (removed by the cut)
FILL_DEPTH_SAMPLES = 100


def _load(group, sections_dir, report):
    fname = config.STAGE3_SECTION_FILES[group]
    path = sections_dir / fname
    if not path.is_file():
        raise WindowBuildError(f"Section DXF not found: {path}", report)
    try:
        profile = load_profile(path, normalize_origin=True)
        return orient_profile(profile, config.SECTION_ORIENTATION.get(group, "as_drawn"))
    except (ProfileError, ValueError) as exc:
        raise WindowBuildError(f"{fname}: {exc}", report)


def _place(solid, profile, group, origin, across, direction):
    """Apply flips, then map the +Z extrusion onto (origin, across, direction)."""
    if config.GROUP_ACROSS_FLIP.get(group):
        solid = solid.mirror("YZ", (profile.width / 2.0, 0.0, 0.0))
    if config.GROUP_DEPTH_FLIP.get(group):
        solid = solid.mirror("ZX", (0.0, profile.height / 2.0, 0.0))
    plane = cq.Plane(origin=origin, xDir=across, normal=direction)
    return solid.transformShape(plane.rG)


def _member(profile, group, name, origin, across, direction, length, report, oversize=0.0):
    try:
        raw = build_solid(profile, length + 2.0 * oversize)
    except SolidBuildError as exc:
        raise WindowBuildError(f"{name}: {exc}", report)
    z = config.GROUP_Z_OFFSET.get(group, 0.0)
    start = (
        origin[0] - direction[0] * oversize,
        origin[1] - direction[1] * oversize,
        z,
    )
    return _place(raw, profile, group, start, across, direction)


def _finish(shape, name, width, height, report):
    solid = _single_solid(shape, name)
    if not solid.isValid():
        try:
            solid = _single_solid(solid.fix(), name)
        except Exception as exc:
            raise WindowBuildError(f"{name}: invalid solid: {exc}", report)
        if not solid.isValid():
            raise WindowBuildError(f"{name}: solid is invalid after healing", report)

    bb = solid.BoundingBox()
    tol = config.FRAME_BBOX_TOLERANCE
    if bb.xmin < -tol or bb.ymin < -tol or bb.xmax > width + tol or bb.ymax > height + tol:
        raise WindowBuildError(
            f"{name}: outside frame bounds "
            f"(x {bb.xmin:.2f}..{bb.xmax:.2f}, y {bb.ymin:.2f}..{bb.ymax:.2f})", report)
    return solid


def _register(parts, report, name, group, dxf, solid, profile):
    bb = solid.BoundingBox()
    parts[name] = solid
    report["parts"][name] = {
        "group": group,
        "dxf": dxf,
        "across": profile.width,
        "depth": profile.height,
        "volume": solid.Volume(),
        "bbox": {
            "x": [bb.xmin, bb.xmax],
            "y": [bb.ymin, bb.ymax],
            "z": [bb.zmin, bb.zmax],
        },
    }


def _rect_layout(x0, y0, x1, y1):
    """Member placement around a rectangle. depth = direction x across = +Z."""
    return {
        "Bottom": {"origin": (x0, y0), "across": (0.0, 1.0, 0.0), "dir": (1.0, 0.0, 0.0), "length": x1 - x0},
        "Top": {"origin": (x1, y1), "across": (0.0, -1.0, 0.0), "dir": (-1.0, 0.0, 0.0), "length": x1 - x0},
        "Left": {"origin": (x0, y1), "across": (1.0, 0.0, 0.0), "dir": (0.0, -1.0, 0.0), "length": y1 - y0},
        "Right": {"origin": (x1, y0), "across": (-1.0, 0.0, 0.0), "dir": (0.0, 1.0, 0.0), "length": y1 - y0},
    }


def _rect_envelopes(x0, y0, x1, y1, b):
    return {
        "Bottom": [(x0, y0), (x1, y0), (x1 - b, y0 + b), (x0 + b, y0 + b)],
        "Top": [(x0, y1), (x1, y1), (x1 - b, y1 - b), (x0 + b, y1 - b)],
        "Left": [(x0, y0), (x0 + b, y0 + b), (x0 + b, y1 - b), (x0, y1)],
        "Right": [(x1, y0), (x1, y1), (x1 - b, y1 - b), (x1 - b, y0 + b)],
    }


def _add_bead_ring(parts, report, bead, prefix, rect, z_top, width, height):
    x0, y0, x1, y1 = rect
    b = bead.width
    layout = _rect_layout(x0, y0, x1, y1)
    envelopes = _rect_envelopes(x0, y0, x1, y1, b)
    oversize = b + 10.0

    for side in SIDES:
        name = f"{prefix}_{side}"
        spec = layout[side]
        placed = _member(
            bead, "Bead", name, spec["origin"], spec["across"], spec["dir"],
            spec["length"], report, oversize=oversize,
        )
        try:
            envelope = (
                cq.Workplane("XY", origin=(0, 0, -1.0))
                .polyline(envelopes[side]).close()
                .extrude(z_top + 1.0)
                .val()
            )
            cut = placed.intersect(envelope)
        except Exception as exc:
            raise WindowBuildError(f"{name}: mitre cut failed: {exc}", report)

        solid = _finish(cut, name, width, height, report)
        _register(parts, report, name, "Bead", config.STAGE3_SECTION_FILES["Bead"], solid, bead)


# ---------------------------------------------------------------- gap fill

def _face_gap(profile, depth_limit, side):
    """Worst gap between a neighbour's butting face plane and its material.

    side "far":  the face is at across = profile.width (inner face of a frame member).
    side "near": the face is at across = 0.
    The gap is measured over depth 0..depth_limit using the profile outline.
    """
    if depth_limit <= 0.0:
        return 0.0
    pts = profile.outer.points()
    n = len(pts)
    if n < 3:
        return 0.0
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]

    depths = {depth_limit * i / FILL_DEPTH_SAMPLES for i in range(FILL_DEPTH_SAMPLES + 1)}
    depths.update(p[1] for p in pts if 0.0 <= p[1] <= depth_limit)

    worst = 0.0
    for z in sorted(depths):
        xs = []
        for (x0, y0), (x1, y1) in edges:
            if (y0 - z) * (y1 - z) > 0.0:
                continue
            if y0 == y1:
                xs.extend((x0, x1))
            else:
                t = (z - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        if not xs:
            continue
        gap = profile.width - max(xs) if side == "far" else min(xs)
        worst = max(worst, gap)
    return worst


def _end_ext(profile, depth_limit, side):
    """How far a member must reach into this neighbour (0 = no gap)."""
    gap = _face_gap(profile, min(profile.height, depth_limit), side)
    if gap <= FILL_MIN_GAP:
        return 0.0
    return min(profile.width, gap + FILL_MARGIN)


def _frame_profiles(sections_dir):
    """Oriented section profiles of the four frame members."""
    cache = {}
    profiles = {}
    for name in frame_builder.PART_ORDER:
        fname = config.FRAME_SECTION_FILES[name]
        if fname not in cache:
            cache[fname] = load_profile(Path(sections_dir) / fname, normalize_origin=True)
        profiles[name] = orient_profile(cache[fname], frame_builder._orientation_for(name, fname))
    return profiles


def _frame_outline_solid(name, profile, width, height):
    """Solid outline (holes filled) of a frame member in frame coordinates."""
    spec = frame_builder._member_layout(width, height)[name]
    length = spec["outer_length"] + 2.0 * config.MITRE_OVERSIZE
    outline = frame_builder._outline_only(profile)
    return frame_builder._place(build_solid(outline, length), outline, name, spec, length)


def _limiter_polygon(a0, a1, e0, e1, d0, d1, z_big):
    """Polygon (axis, z) that keeps the member span plus each extension.

    An extension beyond a span end is only kept up to the neighbour's depth.
    """
    pts = [(a0 - e0, -1.0)]
    if e0 > 0.0:
        pts += [(a0 - e0, d0), (a0, d0)]
    pts += [(a0, z_big), (a1, z_big)]
    if e1 > 0.0:
        pts += [(a1, d1), (a1 + e1, d1)]
    pts += [(a1 + e1, -1.0)]
    return pts


def _limiter(axis, polygon, width, height):
    if axis == "x":
        return (
            cq.Workplane("XZ", origin=(0.0, height + 1.0, 0.0))
            .polyline(polygon).close()
            .extrude(height + 2.0)
            .val()
        )
    return (
        cq.Workplane("YZ", origin=(-1.0, 0.0, 0.0))
        .polyline(polygon).close()
        .extrude(width + 2.0)
        .val()
    )


def _fill_member(shape, axis, span, ends, width, height, z_top):
    """Trim the extended member to its limiter and cut the neighbours' outlines.

    ends = ((ext, depth, get_outline), (ext, depth, get_outline)) for the low
    and the high end of the span along `axis`.
    """
    (e0, d0, g0), (e1, d1, g1) = ends
    polygon = _limiter_polygon(span[0], span[1], e0, e1, d0, d1, z_top + 1.0)
    result = shape.intersect(_limiter(axis, polygon, width, height))
    for ext, getter in ((e0, g0), (e1, g1)):
        if ext > 0.0:
            result = result.cut(getter())
    return result


def _make_member(profile, group, name, origin, across, direction, length, report,
                 axis, span, ends, width, height, z_top):
    """Build a member; extend it into stepped neighbours when there is a gap."""
    if any(end[0] > 0.0 for end in ends):
        try:
            oversize = max(end[0] for end in ends)
            shape = _member(profile, group, name, origin, across, direction, length,
                            report, oversize=oversize)
            shape = _fill_member(shape, axis, span, ends, width, height, z_top)
            return _finish(shape, name, width, height, report)
        except Exception as exc:
            report["warnings"].append(f"{name}: gap fill skipped: {exc}")
    shape = _member(profile, group, name, origin, across, direction, length, report)
    return _finish(shape, name, width, height, report)


def build_window(width=config.DEFAULT_FRAME_WIDTH, height=config.DEFAULT_FRAME_HEIGHT,
                 sections_dir=None):
    """Return (parts, report). parts maps part name -> cadquery Solid (ordered)."""
    sections_dir = Path(sections_dir) if sections_dir else config.SECTIONS_DIR

    frame_parts, report = build_frame(width, height, sections_dir=sections_dir)
    parts = {}
    for name, solid in frame_parts.items():
        parts[name] = solid
        report["parts"][name]["group"] = "Frame"
    report["stage"] = 3

    a = report["across"]
    aj_l, aj_r = a["Jamb_Left"], a["Jamb_Right"]
    a_h, a_s = a["Head"], a["Sill"]

    mullion = _load("Mullion", sections_dir, report)
    transom = _load("Transom", sections_dir, report)
    bead = _load("Bead", sections_dir, report)

    for group, prof in (("Mullion", mullion), ("Transom", transom), ("Bead", bead)):
        for warning in prof.warnings:
            report["warnings"].append(f"{config.STAGE3_SECTION_FILES[group]}: {warning}")

    sw, g, b = mullion.width, transom.width, bead.width
    cx = width * config.MULLION_X_FRACTION
    ty = height * config.TRANSOM_Y_FRACTION
    x_left, x_right = cx - sw / 2.0, cx + sw / 2.0
    y_lo, y_hi = a_s, height - a_h
    t_lo, t_hi = ty - g / 2.0, ty + g / 2.0

    report["layout"] = {
        "mullion_x": [x_left, x_right],
        "transom_y": [t_lo, t_hi],
        "bead_across": b,
    }

    columns = (("Left", aj_l, x_left), ("Right", x_right, width - aj_r))
    rows = (("Lower", y_lo, t_lo), ("Upper", t_hi, y_hi))
    for row_name, ya, yb in rows:
        for col_name, xa, xb in columns:
            if xb - xa <= 2.0 * b or yb - ya <= 2.0 * b:
                raise WindowBuildError(
                    f"Opening {row_name}_{col_name} is {xb - xa:.1f} x {yb - ya:.1f} mm; "
                    f"it must exceed twice the bead width ({2.0 * b:.1f} mm) in both directions",
                    report)

    depths = list(report["depth"].values())
    depths += [
        mullion.height + config.GROUP_Z_OFFSET.get("Mullion", 0.0),
        transom.height + config.GROUP_Z_OFFSET.get("Transom", 0.0),
        bead.height + config.GROUP_Z_OFFSET.get("Bead", 0.0),
    ]
    z_top = max(depths) + 2.0

    # Frame profiles and lazily built outline solids for the gap fill.
    try:
        fprofiles = _frame_profiles(sections_dir)
    except Exception as exc:
        fprofiles = None
        report["warnings"].append(f"Gap fill skipped: {exc}")

    outline_cache = {}

    def frame_outline(name):
        def getter():
            if name not in outline_cache:
                outline_cache[name] = _frame_outline_solid(name, fprofiles[name], width, height)
            return outline_cache[name]
        return getter

    def no_end():
        return (0.0, 0.0, None)

    def frame_end(name, limit, side="far"):
        if fprofiles is None:
            return no_end()
        prof = fprofiles[name]
        return (_end_ext(prof, limit, side), prof.height, frame_outline(name))

    # Mullion: across +X, runs downward from the head inner face to the sill inner face.
    mullion_outline = None
    if fprofiles is not None:
        try:
            mullion_outline = _member(
                frame_builder._outline_only(mullion), "Mullion", "Mullion_outline",
                (x_left, y_hi, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), y_hi - y_lo, report,
            )
        except Exception as exc:
            report["warnings"].append(f"Mullion outline for gap fill failed: {exc}")

    # Low end = sill, high end = head (span along Y).
    mullion_ends = (
        frame_end("Sill", mullion.height),
        frame_end("Head", mullion.height),
    )
    solid = _make_member(
        mullion, "Mullion", "Mullion", (x_left, y_hi, 0.0),
        (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), y_hi - y_lo, report,
        "y", (y_lo, y_hi), mullion_ends, width, height, z_top,
    )
    _register(parts, report, "Mullion", "Mullion", config.STAGE3_SECTION_FILES["Mullion"], solid, mullion)

    def mullion_end(side):
        if mullion_outline is None:
            return no_end()
        return (_end_ext(mullion, transom.height, side), mullion.height, lambda: mullion_outline)

    # Transoms: across +Y, run along +X between jamb and mullion.
    transom_specs = (
        ("Transom_Left", aj_l, x_left,
         frame_end("Jamb_Left", transom.height), mullion_end("near")),
        ("Transom_Right", x_right, width - aj_r,
         mullion_end("far"), frame_end("Jamb_Right", transom.height)),
    )
    for name, xa, xb, end_lo, end_hi in transom_specs:
        solid = _make_member(
            transom, "Transom", name, (xa, t_lo, 0.0),
            (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), xb - xa, report,
            "x", (xa, xb), (end_lo, end_hi), width, height, z_top,
        )
        _register(parts, report, name, "Transom", config.STAGE3_SECTION_FILES["Transom"], solid, transom)

    # Beads: one mitred ring per opening.
    for row_name, ya, yb in rows:
        for col_name, xa, xb in columns:
            _add_bead_ring(
                parts, report, bead, f"Bead_{row_name}_{col_name}",
                (xa, ya, xb, yb), z_top, width, height,
            )

    return parts, report
