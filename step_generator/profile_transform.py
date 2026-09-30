"""Rotate a loaded section profile by a multiple of 90 degrees.

Profile X = across, profile Y = depth. A section drawn the other way round in
its DXF (across and depth swapped) is turned with this, so it keeps its shape
and is never mirrored. The result stays normalised (bounding-box corner at 0, 0).
"""
from .dxf_profile import Loop, Profile, Segment


def _map_loop(loop, fn):
    if loop.circle is not None:
        cx, cy, r = loop.circle
        nx, ny = fn((cx, cy))
        return Loop(circle=(nx, ny, r))
    segments = [
        Segment(
            kind=s.kind,
            start=fn(s.start),
            end=fn(s.end),
            mid=fn(s.mid) if s.mid is not None else None,
        )
        for s in loop.segments
    ]
    return Loop(segments=segments)


def rotate_profile(profile, degrees):
    """Return a new Profile turned counter-clockwise by `degrees` (0, 90, 180, 270)."""
    turns = int(round(degrees / 90.0)) % 4
    if turns == 0:
        return profile

    w, h = profile.width, profile.height
    if turns == 1:
        def fn(p):
            return (h - p[1], p[0])
        new_w, new_h = h, w
    elif turns == 2:
        def fn(p):
            return (w - p[0], h - p[1])
        new_w, new_h = w, h
    else:
        def fn(p):
            return (p[1], w - p[0])
        new_w, new_h = h, w

    return Profile(
        outer=_map_loop(profile.outer, fn),
        holes=[_map_loop(hole, fn) for hole in profile.holes],
        width=new_w,
        height=new_h,
        normalized=profile.normalized,
        skipped=profile.skipped,
        warnings=profile.warnings,
    )


def swap_axes(profile):
    """Return a new Profile with (x, y) -> (y, x).

    Drawn Y becomes across (0 = outer edge), drawn X becomes depth (0 = front
    face, z = 0). Used for sections drawn with depth along X.
    """
    def fn(p):
        return (p[1], p[0])

    return Profile(
        outer=_map_loop(profile.outer, fn),
        holes=[_map_loop(hole, fn) for hole in profile.holes],
        width=profile.height,
        height=profile.width,
        normalized=profile.normalized,
        skipped=profile.skipped,
        warnings=profile.warnings,
    )


ORIENTATIONS = ("as_drawn", "swap", "rot90", "rot180", "rot270")


def orient_profile(profile, mode="as_drawn"):
    """Bring a drawn section onto the shared convention.

    Shared convention: profile X = across (0 = outer edge of the frame),
    profile Y = depth (0 = front / exterior face at z = 0).

    as_drawn : X is already across, Y is already depth
    swap     : across = drawn Y, depth = drawn X
    rot90    : across = height - drawn Y, depth = drawn X
    rot180   : across = width - drawn X, depth = height - drawn Y
    rot270   : across = drawn Y, depth = width - drawn X
    """
    mode = (mode or "as_drawn").lower()
    if mode == "as_drawn":
        return profile
    if mode == "swap":
        return swap_axes(profile)
    if mode == "rot90":
        return rotate_profile(profile, 90)
    if mode == "rot180":
        return rotate_profile(profile, 180)
    if mode == "rot270":
        return rotate_profile(profile, 270)
    raise ValueError(f"Unknown section orientation '{mode}'; use one of {ORIENTATIONS}")
