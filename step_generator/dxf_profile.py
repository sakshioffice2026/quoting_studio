"""Read a 2D section DXF into clean closed loops (outer + holes)."""
import math
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf

from . import config


class ProfileError(Exception):
    pass


# Entities that carry no geometry for the profile and are safely ignored.
_IGNORED_TYPES = {
    "TEXT", "MTEXT", "DIMENSION", "HATCH", "POINT", "LEADER", "MLEADER",
    "VIEWPORT", "IMAGE", "ATTRIB", "ATTDEF", "TOLERANCE", "WIPEOUT",
}


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _close(a, b, tol):
    return _dist(a, b) <= tol


@dataclass
class Segment:
    kind: str            # "line" or "arc"
    start: tuple
    end: tuple
    mid: tuple = None    # a point on the arc (arc only)

    def reversed(self):
        return Segment(kind=self.kind, start=self.end, end=self.start, mid=self.mid)


def _circumcenter(p1, p2, p3):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3
    ux = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    uy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return ux, uy


def arc_points(p1, pm, p2, samples):
    """Points along the three-point arc p1 -> pm -> p2 (both ends included)."""
    c = _circumcenter(p1, pm, p2)
    if c is None:
        return [p1, p2]
    cx, cy = c
    r = math.hypot(p1[0] - cx, p1[1] - cy)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    am = math.atan2(pm[1] - cy, pm[0] - cx)
    a2 = math.atan2(p2[1] - cy, p2[0] - cx)
    tau = 2.0 * math.pi
    ccw_mid = (am - a1) % tau
    ccw_end = (a2 - a1) % tau
    if ccw_mid <= ccw_end:
        sweep = ccw_end
    else:
        sweep = -((a1 - a2) % tau)
    pts = [(cx + r * math.cos(a1 + sweep * i / samples),
            cy + r * math.sin(a1 + sweep * i / samples)) for i in range(samples + 1)]
    pts[0] = p1
    pts[-1] = p2
    return pts


def _shoelace(pts):
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def point_in_polygon(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


@dataclass
class Loop:
    segments: list = field(default_factory=list)
    circle: tuple = None     # (cx, cy, r) for a full-circle loop

    def points(self, samples=None):
        samples = samples or config.ARC_SAMPLES
        if self.circle is not None:
            cx, cy, r = self.circle
            n = max(samples * 4, 96)
            return [(cx + r * math.cos(2 * math.pi * i / n),
                     cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        pts = []
        for seg in self.segments:
            if seg.kind == "arc":
                pts.extend(arc_points(seg.start, seg.mid, seg.end, samples)[:-1])
            else:
                pts.append(seg.start)
        return pts

    def area(self):
        if self.circle is not None:
            return math.pi * self.circle[2] ** 2
        return abs(_shoelace(self.points()))

    def bbox(self):
        if self.circle is not None:
            cx, cy, r = self.circle
            return cx - r, cy - r, cx + r, cy + r
        pts = self.points(config.BBOX_SAMPLES)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def translated(self, dx, dy):
        if self.circle is not None:
            cx, cy, r = self.circle
            return Loop(circle=(cx + dx, cy + dy, r))
        segs = []
        for s in self.segments:
            mid = (s.mid[0] + dx, s.mid[1] + dy) if s.mid is not None else None
            segs.append(Segment(kind=s.kind,
                                start=(s.start[0] + dx, s.start[1] + dy),
                                end=(s.end[0] + dx, s.end[1] + dy),
                                mid=mid))
        return Loop(segments=segs)


@dataclass
class Profile:
    outer: Loop
    holes: list
    width: float
    height: float
    normalized: bool
    skipped: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def area(self):
        return self.outer.area() - sum(h.area() for h in self.holes)


# ---------------------------------------------------------------- reading

def _check_extrusion(e):
    if e.dxf.hasattr("extrusion"):
        z = e.dxf.extrusion.z
        if abs(z - 1.0) > 1e-9:
            raise ProfileError(
                f"{e.dxftype()} uses a flipped/tilted extrusion vector; not supported"
            )


def _polyline_segments(e, s, tol):
    if e.dxftype() == "LWPOLYLINE":
        verts = [(x * s, y * s, b) for x, y, b in e.get_points("xyb")]
        closed = bool(e.closed)
    else:
        if not e.is_2d_polyline:
            raise ProfileError("3D POLYLINE is not supported")
        verts = [(v.dxf.location.x * s, v.dxf.location.y * s, v.dxf.bulge)
                 for v in e.vertices]
        closed = bool(e.is_closed)

    if len(verts) < 2:
        return [], False
    if not closed and len(verts) > 2 and _close(verts[0][:2], verts[-1][:2], tol):
        closed = True
        verts = verts[:-1]

    count = len(verts) if closed else len(verts) - 1
    segs = []
    for i in range(count):
        x1, y1, b = verts[i]
        x2, y2, _ = verts[(i + 1) % len(verts)]
        p1, p2 = (x1, y1), (x2, y2)
        if _dist(p1, p2) <= config.MIN_SEGMENT_LENGTH:
            continue
        if abs(b) < config.BULGE_LINE_THRESHOLD:
            segs.append(Segment(kind="line", start=p1, end=p2))
        else:
            # Bulge > 0 = counter-clockwise arc, which lies to the right of p1->p2.
            mid = ((x1 + x2) / 2.0 + b * (y2 - y1) / 2.0,
                   (y1 + y2) / 2.0 - b * (x2 - x1) / 2.0)
            segs.append(Segment(kind="arc", start=p1, end=p2, mid=mid))
    return segs, closed


def _arc_segment(e, s):
    c = e.dxf.center
    cx, cy, r = c.x * s, c.y * s, e.dxf.radius * s
    sa = math.radians(e.dxf.start_angle)
    ea = math.radians(e.dxf.end_angle)
    if ea <= sa:
        ea += 2 * math.pi
    ma = (sa + ea) / 2.0
    return Segment(
        kind="arc",
        start=(cx + r * math.cos(sa), cy + r * math.sin(sa)),
        end=(cx + r * math.cos(ea), cy + r * math.sin(ea)),
        mid=(cx + r * math.cos(ma), cy + r * math.sin(ma)),
    )


def _snap(loop, tol):
    """Make consecutive segments share exactly the same endpoint."""
    segs = loop.segments
    for i in range(len(segs)):
        prev = segs[i - 1]
        cur = segs[i]
        gap = _dist(prev.end, cur.start)
        if gap > tol:
            raise ProfileError(f"Gap of {gap:.4f} mm between consecutive edges")
        cur.start = prev.end


def _chain(open_segments, tol):
    remaining = list(open_segments)
    loops = []
    while remaining:
        chain = [remaining.pop(0)]
        progressed = True
        while progressed:
            if len(chain) >= 2 and _close(chain[0].start, chain[-1].end, tol):
                break
            progressed = False
            for i, seg in enumerate(remaining):
                if _close(seg.start, chain[-1].end, tol):
                    chain.append(remaining.pop(i))
                elif _close(seg.end, chain[-1].end, tol):
                    chain.append(remaining.pop(i).reversed())
                elif _close(seg.end, chain[0].start, tol):
                    chain.insert(0, remaining.pop(i))
                elif _close(seg.start, chain[0].start, tol):
                    chain.insert(0, remaining.pop(i).reversed())
                else:
                    continue
                progressed = True
                break
        if not _close(chain[0].start, chain[-1].end, tol):
            raise ProfileError(
                "Open outline: edges starting near "
                f"({chain[0].start[0]:.3f}, {chain[0].start[1]:.3f}) do not form a closed loop"
            )
        loops.append(Loop(segments=chain))
    return loops


def read_loops(dxf_path, layers=None):
    path = Path(dxf_path)
    if not path.is_file():
        raise ProfileError(f"DXF not found: {path}")
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as exc:
        raise ProfileError(f"Could not read DXF {path.name}: {exc}")

    tol = config.JOIN_TOLERANCE
    s = config.UNIT_SCALE
    loops = []
    open_segments = []
    open_polylines = []     # open polylines, kept apart so a lone one can be auto-closed
    has_loose_entities = False
    skipped = {}
    warnings = []

    for e in doc.modelspace():
        t = e.dxftype()
        if layers and e.dxf.layer not in layers:
            continue
        if t in _IGNORED_TYPES:
            skipped[t] = skipped.get(t, 0) + 1
            continue
        if t == "INSERT":
            raise ProfileError("Block reference (INSERT) found; explode blocks in the DXF first")
        _check_extrusion(e)

        if t in ("LWPOLYLINE", "POLYLINE"):
            segs, closed = _polyline_segments(e, s, tol)
            if closed and segs:
                loops.append(Loop(segments=segs))
            elif segs:
                open_polylines.append(segs)
        elif t == "LINE":
            has_loose_entities = True
            p1 = (e.dxf.start.x * s, e.dxf.start.y * s)
            p2 = (e.dxf.end.x * s, e.dxf.end.y * s)
            if _dist(p1, p2) > config.MIN_SEGMENT_LENGTH:
                open_segments.append(Segment(kind="line", start=p1, end=p2))
        elif t == "ARC":
            has_loose_entities = True
            open_segments.append(_arc_segment(e, s))
        elif t == "CIRCLE":
            c = e.dxf.center
            loops.append(Loop(circle=(c.x * s, c.y * s, e.dxf.radius * s)))
        else:
            raise ProfileError(f"Unsupported entity type in profile: {t}")

    if has_loose_entities:
        # Polylines may continue into loose LINE/ARC edges, so chain them together.
        for segs in open_polylines:
            open_segments.extend(segs)
    else:
        # Only polylines present: an open one is auto-closed with a straight edge.
        for segs in open_polylines:
            gap = _dist(segs[-1].end, segs[0].start)
            if gap > tol:
                segs.append(Segment(kind="line", start=segs[-1].end, end=segs[0].start))
                warnings.append(
                    f"Open polyline auto-closed with a {gap:.3f} mm straight edge "
                    f"from ({segs[-1].start[0]:.3f}, {segs[-1].start[1]:.3f}) to "
                    f"({segs[-1].end[0]:.3f}, {segs[-1].end[1]:.3f}); fix the DXF at source"
                )
            loops.append(Loop(segments=segs))

    loops.extend(_chain(open_segments, tol))
    for loop in loops:
        if loop.circle is None:
            _snap(loop, tol)
    if not loops:
        raise ProfileError("No closed outline found in DXF")
    return loops, skipped, warnings


def classify_loops(loops):
    """Largest loop = outer boundary; every other loop must be a hole inside it."""
    ordered = sorted(loops, key=lambda l: l.area(), reverse=True)
    outer = ordered[0]
    holes = ordered[1:]
    outer_poly = outer.points()
    hole_polys = [h.points() for h in holes]

    for h, poly in zip(holes, hole_polys):
        probe = poly[0]
        if not point_in_polygon(probe, outer_poly):
            raise ProfileError(
                "DXF holds separate shapes (a loop outside the main outline); "
                "one section per DXF is required"
            )
        for other, opoly in zip(holes, hole_polys):
            if other is not h and point_in_polygon(probe, opoly):
                raise ProfileError("Nested loops (shape inside a hole) are not supported")
    return outer, holes


def load_profile(dxf_path, normalize_origin=True, layers=None):
    loops, skipped, warnings = read_loops(dxf_path, layers=layers)
    outer, holes = classify_loops(loops)

    min_x, min_y, max_x, max_y = outer.bbox()
    if normalize_origin:
        dx, dy = -min_x, -min_y
        outer = outer.translated(dx, dy)
        holes = [h.translated(dx, dy) for h in holes]
        min_x, min_y, max_x, max_y = outer.bbox()

    return Profile(
        outer=outer,
        holes=holes,
        width=max_x - min_x,
        height=max_y - min_y,
        normalized=normalize_origin,
        skipped=skipped,
        warnings=warnings,
    )
