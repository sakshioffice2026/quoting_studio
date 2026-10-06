"""Layout model for the STEP generator: panes -> openings and dividing members.

Input is the JSON written by app/services/cad/step_generator_service.py:

    {
      "version": 1,
      "kind": "window" | "door",
      "door_type": "single" | "double",      (doors only)
      "width": 1200.0, "height": 1400.0,      (outer size, mm)
      "y_origin": "top" | "bottom",           (default "top")
      "panes": [{"id", "x", "y", "w", "h", "opener", "infill"}, ...]
    }

Pane x, y, w, h are normalised 0..1 over the outer frame.

Output coordinates are millimetres, X = width, Y = height, origin at the outer
bottom-left corner (the generator's frame coordinates). Every pane edge that is
not on the outer frame is a divider centre line. Collinear pane edges are
merged into one member:

    vertical member    kind "mullion"   pos = x, span = (y_lo, y_hi)
    horizontal member  kind "transom"   pos = y, span = (x_lo, x_hi)

Vertical members run through crossings; horizontal members are split where a
vertical member crosses them. A member that ends on the outer frame has end
"frame"; a member that ends on another divider has end "member".

This covers plain grids (full-length dividers) and T-splits (dividers that stop
on another divider).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TOL_MM = 0.5            # coordinates closer than this are the same line
AREA_TOLERANCE = 0.005  # allowed relative error between pane area and frame area


class LayoutError(ValueError):
    pass


@dataclass(frozen=True)
class Opening:
    """One pane cell between divider centre lines (frame coordinates, mm)."""
    id: str
    x0: float
    y0: float
    x1: float
    y1: float
    opener: str = "Fixed"
    infill: str = "glass"

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class Member:
    """A divider centre line with its span along its own axis (mm)."""
    kind: str           # "mullion" | "transom"
    pos: float          # x for a mullion, y for a transom
    a0: float           # span start (y for a mullion, x for a transom)
    a1: float           # span end
    lo_end: str         # "frame" | "member"
    hi_end: str

    @property
    def length(self) -> float:
        return self.a1 - self.a0


@dataclass
class Layout:
    kind: str
    width: float
    height: float
    door_type: str = "single"
    openings: list = field(default_factory=list)
    mullions: list = field(default_factory=list)
    transoms: list = field(default_factory=list)

    @property
    def members(self) -> list:
        return list(self.mullions) + list(self.transoms)

    @property
    def is_grid(self) -> bool:
        """True when every divider runs the full frame (no T-splits)."""
        full_v = all(
            m.lo_end == "frame" and m.hi_end == "frame" for m in self.mullions)
        horizontal = {}
        for t in self.transoms:
            horizontal.setdefault(round(t.pos, 1), []).append(t)
        full_h = all(
            min(t.a0 for t in group) <= TOL_MM
            and max(t.a1 for t in group) >= self.width - TOL_MM
            for group in horizontal.values())
        return full_v and full_h


# ------------------------------------------------------------------ helpers

def _number(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LayoutError(f"{name} is not a number: {value!r}")
    if number != number:
        raise LayoutError(f"{name} is NaN")
    return number


def _snap_map(values, lo, hi):
    """Map every value to a cluster representative; ends snap to lo / hi."""
    ordered = sorted(set(values))
    clusters = []
    for v in ordered:
        if clusters and v - clusters[-1][-1] <= TOL_MM:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    mapping = {}
    for cluster in clusters:
        mean = sum(cluster) / len(cluster)
        if abs(mean - lo) <= TOL_MM:
            mean = lo
        elif abs(mean - hi) <= TOL_MM:
            mean = hi
        for v in cluster:
            mapping[v] = mean
    return mapping


def _merge(intervals):
    """Merge overlapping or touching (a0, a1) intervals."""
    result = []
    for a0, a1 in sorted(intervals):
        if result and a0 <= result[-1][1] + TOL_MM:
            result[-1][1] = max(result[-1][1], a1)
        else:
            result.append([a0, a1])
    return [(a0, a1) for a0, a1 in result]


def _group(edges):
    """edges: [(pos, a0, a1)] -> {pos: merged intervals}, positions clustered."""
    groups = {}
    for pos, a0, a1 in sorted(edges):
        key = None
        for existing in groups:
            if abs(existing - pos) <= TOL_MM:
                key = existing
                break
        if key is None:
            key = pos
            groups[key] = []
        groups[key].append((a0, a1))
    return {pos: _merge(items) for pos, items in groups.items()}


def _end_kind(value, lo, hi):
    return "frame" if value <= lo + TOL_MM or value >= hi - TOL_MM else "member"


# ------------------------------------------------------------------- parse

def _read_panes(data, width, height):
    raw = data.get("panes") or []
    if not raw:
        raise LayoutError("layout has no panes")

    y_top = str(data.get("y_origin", "top")).lower() != "bottom"
    rects = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise LayoutError(f"pane {index + 1} is not an object")
        pid = str(item.get("id", f"p{index + 1}"))
        x = _number(item.get("x"), f"pane '{pid}'.x")
        y = _number(item.get("y"), f"pane '{pid}'.y")
        w = _number(item.get("w"), f"pane '{pid}'.w")
        h = _number(item.get("h"), f"pane '{pid}'.h")
        if w <= 0 or h <= 0:
            raise LayoutError(f"pane '{pid}' has zero or negative size")
        if x < -1e-6 or y < -1e-6 or x + w > 1.0001 or y + h > 1.0001:
            raise LayoutError(f"pane '{pid}' is outside the frame")

        x0, x1 = x * width, (x + w) * width
        if y_top:
            y0, y1 = height - (y + h) * height, height - y * height
        else:
            y0, y1 = y * height, (y + h) * height

        rects.append({
            "id": pid,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "opener": str(item.get("opener", item.get("opening", "Fixed")) or "Fixed"),
            "infill": str(item.get("infill", "glass") or "glass"),
        })
    return rects


def _snap_rects(rects, width, height):
    xmap = _snap_map([r[k] for r in rects for k in ("x0", "x1")], 0.0, width)
    ymap = _snap_map([r[k] for r in rects for k in ("y0", "y1")], 0.0, height)
    for r in rects:
        r["x0"], r["x1"] = xmap[r["x0"]], xmap[r["x1"]]
        r["y0"], r["y1"] = ymap[r["y0"]], ymap[r["y1"]]
        if r["x1"] - r["x0"] <= TOL_MM or r["y1"] - r["y0"] <= TOL_MM:
            raise LayoutError(f"pane '{r['id']}' collapses after snapping")


def _check_tiling(rects, width, height):
    total = sum((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) for r in rects)
    frame = width * height
    if abs(total - frame) > AREA_TOLERANCE * frame:
        raise LayoutError(
            f"panes cover {total / frame:.3f} of the frame; they must tile it exactly")

    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            ox = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            oy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
            if ox > TOL_MM and oy > TOL_MM:
                raise LayoutError(f"panes '{a['id']}' and '{b['id']}' overlap")


def _build_members(rects, width, height):
    v_edges, h_edges = [], []
    for r in rects:
        for x in (r["x0"], r["x1"]):
            if TOL_MM < x < width - TOL_MM:
                v_edges.append((x, r["y0"], r["y1"]))
        for y in (r["y0"], r["y1"]):
            if TOL_MM < y < height - TOL_MM:
                h_edges.append((y, r["x0"], r["x1"]))

    mullions = []
    for x, spans in sorted(_group(v_edges).items()):
        for y0, y1 in spans:
            mullions.append(Member(
                "mullion", x, y0, y1,
                _end_kind(y0, 0.0, height), _end_kind(y1, 0.0, height)))

    transoms = []
    for y, spans in sorted(_group(h_edges).items()):
        for x0, x1 in spans:
            cuts = sorted(
                m.pos for m in mullions
                if x0 + TOL_MM < m.pos < x1 - TOL_MM
                and m.a0 + TOL_MM < y < m.a1 - TOL_MM)
            points = [x0] + cuts + [x1]
            for i in range(len(points) - 1):
                a0, a1 = points[i], points[i + 1]
                lo = _end_kind(a0, 0.0, width) if i == 0 else "member"
                hi = _end_kind(a1, 0.0, width) if i == len(points) - 2 else "member"
                transoms.append(Member("transom", y, a0, a1, lo, hi))
    return mullions, transoms


def parse_layout(data) -> Layout:
    if not isinstance(data, dict):
        raise LayoutError("layout must be a JSON object")

    kind = str(data.get("kind", "window")).lower()
    if kind not in ("window", "door"):
        raise LayoutError(f"unknown kind: {kind!r}")

    width = _number(data.get("width"), "width")
    height = _number(data.get("height"), "height")
    if width <= 0 or height <= 0:
        raise LayoutError("width and height must be positive")

    door_type = "single"
    if kind == "door":
        door_type = "double" if str(data.get("door_type", "single")).lower() == "double" else "single"

    rects = _read_panes(data, width, height)
    _snap_rects(rects, width, height)
    _check_tiling(rects, width, height)
    mullions, transoms = _build_members(rects, width, height)

    openings = [
        Opening(r["id"], r["x0"], r["y0"], r["x1"], r["y1"], r["opener"], r["infill"])
        for r in sorted(rects, key=lambda r: (-r["y1"], r["x0"]))
    ]
    return Layout(
        kind=kind, width=width, height=height, door_type=door_type,
        openings=openings, mullions=mullions, transoms=transoms)


def load_layout(path) -> Layout:
    path = Path(path)
    if not path.is_file():
        raise LayoutError(f"layout file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise LayoutError(f"layout file unreadable: {exc}")
    return parse_layout(data)
