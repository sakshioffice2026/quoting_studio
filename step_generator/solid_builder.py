"""Profile loops -> one extruded cadquery solid (outer boundary with holes)."""
import cadquery as cq


class SolidBuildError(Exception):
    pass


def _add_loop(wp, loop):
    if loop.circle is not None:
        cx, cy, r = loop.circle
        return wp.moveTo(cx, cy).circle(r)

    first = loop.segments[0]
    wp = wp.moveTo(first.start[0], first.start[1])
    for seg in loop.segments:
        if seg.kind == "line":
            wp = wp.lineTo(seg.end[0], seg.end[1])
        else:
            wp = wp.threePointArc(seg.mid, seg.end)
    return wp.close()


def build_solid(profile, length):
    """Extrude the profile along +Z by `length` mm and return a single Solid."""
    if length <= 0:
        raise SolidBuildError("Length must be greater than zero")

    wp = cq.Workplane("XY")
    for loop in [profile.outer] + list(profile.holes):
        wp = _add_loop(wp, loop)

    try:
        result = wp.extrude(length)
    except Exception as exc:
        raise SolidBuildError(f"Extrusion failed: {exc}")

    solids = result.solids().vals()
    if len(solids) != 1:
        raise SolidBuildError(f"Expected 1 solid, got {len(solids)}")
    return solids[0]
