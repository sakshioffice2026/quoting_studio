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
