"""Authoritative parametric window/door geometry.

`design_json` is the source of truth. Every fabrication/export path should
consume :func:`build_geometry` rather than rebuilding pane/member placement.
Legacy Pane rows are only a compatibility projection of this model.

Curved-glass support:
- rectangle: rectangular glass
- circular: elliptical/circular glass geometry derived from the pane bounds
- arched/gothic: the existing pane bounds are preserved; specialised curved
  profiles can consume ``WindowGeometry.shape`` and ``arch_rise_mm``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Profile:
    name: str = "DEFAULT"
    bar: float = 58.0
    depth: float = 70.0
    wall: float = 4.0
    rebate_w: float = 15.0
    rebate_d: float = 20.0
    loops: Any = None


@dataclass(frozen=True)
class PaneGeometry:
    id: str
    x: float
    y: float
    w: float
    h: float
    opening: str = "Fixed"
    glazing: str = "Double, Low-E"
    infill: str = "glass"
    glazing_bars: tuple = ()

    @property
    def y_bottom(self) -> float:
        return 1.0 - self.y - self.h


@dataclass(frozen=True)
class GlassGeometry:
    """Actual glass boundary geometry.

    Coordinates are normalised to the same unit-square coordinate system as
    PaneGeometry. For circular glass, x/y represent the centre and w/h are
    the full bounding-box dimensions.
    """
    id: str
    shape: str
    x: float
    y: float
    w: float
    h: float
    radius_x: float = 0.0
    radius_y: float = 0.0
    glazing: str = "Double, Low-E"
    infill: str = "glass"

    @property
    def center_x(self) -> float:
        return self.x

    @property
    def center_y(self) -> float:
        return self.y


@dataclass(frozen=True)
class MemberGeometry:
    id: str
    kind: str                 # frame | mullion | transom
    x: float                  # normalised model coordinate, origin bottom-left
    y: float
    length: float             # normalised length in member direction
    orientation: str          # horizontal | vertical


@dataclass(frozen=True)
class WindowGeometry:
    width_mm: float
    height_mm: float
    profile: Profile
    panes: tuple
    glass: tuple
    members: tuple
    design: dict
    frame_colour_hex: str = "#6a6a6c"
    shape: str = "rectangle"
    arch_rise_mm: float = 0.0

    @property
    def is_curved(self) -> bool:
        """True for any non-rectangular frame shape."""
        return self.shape in ("arched", "gothic", "circular")

    @property
    def bar(self) -> float:
        return self.profile.bar

    @property
    def depth(self) -> float:
        return self.profile.depth


def _parse_design(window) -> dict:
    raw = getattr(window, "design_json", None)
    if isinstance(raw, dict):
        return raw
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (TypeError, ValueError) as exc:
            raise ValueError("window.design_json is not valid JSON") from exc
    return {}


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_profile(tenant_id, material: str = "Aluminium", window=None) -> Profile:
    """Resolve the same profile definition for all export formats."""
    profile = Profile()
    if not tenant_id:
        return profile

    try:
        from ..models.cad_profile import CadProfile

        q = CadProfile.query.filter_by(
            tenant_id=tenant_id,
            material=material,
            is_active=True,
            is_default=True,
        ).first()

        if q is None:
            q = CadProfile.query.filter_by(
                tenant_id=tenant_id,
                is_active=True,
            ).first()

        if q:
            loops = None
            if q.geometry_json:
                try:
                    parsed = json.loads(q.geometry_json)
                    loops = parsed if parsed else None
                except (TypeError, ValueError):
                    logger.warning(
                        "Invalid geometry_json for CadProfile %s",
                        q.id,
                    )

            return Profile(
                name=q.code or q.name or "PROFILE",
                bar=_number(q.bar_width_mm, profile.bar),
                depth=_number(q.depth_mm, profile.depth),
                wall=_number(
                    getattr(q, "wall_thickness_mm", None),
                    profile.wall,
                ),
                rebate_w=_number(
                    getattr(q, "rebate_w_mm", None),
                    profile.rebate_w,
                ),
                rebate_d=_number(
                    getattr(q, "rebate_d_mm", None),
                    profile.rebate_d,
                ),
                loops=loops,
            )

    except Exception as exc:
        logger.warning("Canonical profile lookup failed: %s", exc)

    return profile


def _design_panes(design: dict) -> list[PaneGeometry]:
    """Build PaneGeometry list from design_json['panes'|'cells'].

    Required x/y/w/h values are validated instead of silently defaulting.
    """
    raw = design.get("panes") or design.get("cells") or []
    panes = []

    for index, p in enumerate(raw):
        if not isinstance(p, dict):
            continue

        pid = str(
            p.get("id", p.get("cellKey", f"p{index + 1}"))
        )

        for key in ("x", "y", "w", "h"):
            if p.get(key) is None:
                raise ValueError(
                    f"pane '{pid}' is missing required field '{key}' "
                    "in design_json — cannot build geometry"
                )

        x = _number(p.get("x"), None)
        y = _number(p.get("y"), None)
        w = _number(p.get("w"), None)
        h = _number(p.get("h"), None)

        if x is None or y is None or w is None or h is None:
            raise ValueError(
                f"pane '{pid}' has non-numeric x/y/w/h in design_json"
            )

        if x < 0 or y < 0 or (x + w) > 1.0001 or (y + h) > 1.0001:
            raise ValueError(
                f"pane '{pid}' geometry out of bounds: "
                f"x={x}, y={y}, w={w}, h={h}"
            )

        panes.append(
            PaneGeometry(
                id=pid,
                x=x,
                y=y,
                w=w,
                h=h,
                opening=str(
                    p.get("opening", p.get("opener", "Fixed")) or "Fixed"
                ),
                glazing=str(
                    p.get(
                        "glazing",
                        p.get("glazingType", "Double, Low-E"),
                    )
                    or "Double, Low-E"
                ),
                infill=str(
                    p.get("infill", "glass") or "glass"
                ),
                glazing_bars=tuple(
                    p.get("glazingBars") or ()
                ),
            )
        )

    return panes


def _legacy_panes(window_panes) -> list[PaneGeometry]:
    result = []

    for index, p in enumerate(window_panes or []):
        result.append(
            PaneGeometry(
                id=str(
                    getattr(p, "cell_key", f"p{index + 1}")
                ),
                x=float(getattr(p, "x_norm", 0.0)),
                y=float(getattr(p, "y_norm", 0.0)),
                w=float(getattr(p, "w_norm", 1.0)),
                h=float(getattr(p, "h_norm", 1.0)),
                opening=str(
                    getattr(p, "opener_type", "Fixed") or "Fixed"
                ),
                glazing=str(
                    getattr(p, "glazing_type", "Double, Low-E")
                    or "Double, Low-E"
                ),
                infill=str(
                    getattr(p, "infill", "glass") or "glass"
                ),
            )
        )

    return result


def _pane_key(p: PaneGeometry):
    return (
        p.id,
        round(p.x, 9),
        round(p.y, 9),
        round(p.w, 9),
        round(p.h, 9),
        p.opening,
        p.glazing,
        p.infill,
    )


def _glass_geometry(
    panes: list[PaneGeometry],
    shape: str,
) -> list[GlassGeometry]:
    """Create actual glass boundaries from pane bounds and window shape.

    For circular windows the pane rectangle is treated only as a bounding
    box. The actual glass is represented as a circle/ellipse centred inside
    that box.

    If width == height, radius_x == radius_y and the result is a true circle.
    If width != height, the result is an ellipse, which is safer than
    distorting a non-square circular window definition.
    """
    result = []

    for pane in panes:
        if shape == "circular":
            center_x = pane.x + pane.w / 2.0
            center_y = pane.y + pane.h / 2.0

            result.append(
                GlassGeometry(
                    id=pane.id,
                    shape="circular",
                    x=center_x,
                    y=center_y,
                    w=pane.w,
                    h=pane.h,
                    radius_x=pane.w / 2.0,
                    radius_y=pane.h / 2.0,
                    glazing=pane.glazing,
                    infill=pane.infill,
                )
            )
        else:
            result.append(
                GlassGeometry(
                    id=pane.id,
                    shape="rectangle",
                    x=pane.x,
                    y=pane.y,
                    w=pane.w,
                    h=pane.h,
                    glazing=pane.glazing,
                    infill=pane.infill,
                )
            )

    return result


def legacy_panes_from_design(window) -> list[dict]:
    """Return Pane-compatible dictionaries derived only from design_json."""
    panes = _design_panes(_parse_design(window))

    return [
        {
            "id": p.id,
            "x": p.x,
            "y": p.y,
            "w": p.w,
            "h": p.h,
            "opener": p.opening,
            "glazing": p.glazing,
            "infill": p.infill,
        }
        for p in panes
    ]


def sync_legacy_panes(window, Pane, db) -> int:
    """Rebuild the legacy Pane table from design_json, atomically.

    There is deliberately no path from Pane -> design_json.
    """
    design = _parse_design(window)
    panes = _design_panes(design)

    Pane.query.filter_by(window_id=window.id).delete()

    for p in panes:
        db.session.add(
            Pane(
                window_id=window.id,
                cell_key=p.id,
                x_norm=p.x,
                y_norm=p.y,
                w_norm=p.w,
                h_norm=p.h,
                opener_type=p.opening,
                glazing_type=p.glazing,
                infill=p.infill,
            )
        )

    return len(panes)


def assert_legacy_panes_match(window, window_panes) -> None:
    """Fail loudly if compatibility data no longer matches design_json."""
    design_panes = _design_panes(_parse_design(window))

    if not design_panes:
        return

    legacy = _legacy_panes(window_panes)

    if sorted(map(_pane_key, design_panes)) != sorted(
        map(_pane_key, legacy)
    ):
        raise ValueError(
            "Legacy Pane rows do not match window.design_json; "
            "rebuild them before export"
        )


def _unique(values):
    return sorted(
        set(round(float(v), 9) for v in values)
    )


def _members(
    panes: list[PaneGeometry],
) -> list[MemberGeometry]:
    """Derive mullions/transoms from pane boundaries."""
    xs = _unique(
        [0.0, 1.0]
        + [p.x for p in panes]
        + [p.x + p.w for p in panes]
    )

    ys = _unique(
        [0.0, 1.0]
        + [p.y_bottom for p in panes]
        + [p.y_bottom + p.h for p in panes]
    )

    members = [
        MemberGeometry(
            "frame-bottom",
            "frame",
            0.0,
            0.0,
            1.0,
            "horizontal",
        ),
        MemberGeometry(
            "frame-top",
            "frame",
            0.0,
            1.0,
            1.0,
            "horizontal",
        ),
        MemberGeometry(
            "frame-left",
            "frame",
            0.0,
            0.0,
            1.0,
            "vertical",
        ),
        MemberGeometry(
            "frame-right",
            "frame",
            1.0,
            0.0,
            1.0,
            "vertical",
        ),
    ]

    for x in xs:
        if 0.0 < x < 1.0:
            covered = [
                (p.y_bottom, p.y_bottom + p.h)
                for p in panes
                if (
                    abs((p.x + p.w) - x) < 1e-9
                    or abs(p.x - x) < 1e-9
                )
            ]

            if covered:
                y0 = min(a for a, _ in covered)
                y1 = max(b for _, b in covered)

                members.append(
                    MemberGeometry(
                        f"mullion-{x:g}",
                        "mullion",
                        x,
                        y0,
                        y1 - y0,
                        "vertical",
                    )
                )

    for y in ys:
        if 0.0 < y < 1.0:
            covered = [
                (p.x, p.x + p.w)
                for p in panes
                if (
                    abs(p.y_bottom - y) < 1e-9
                    or abs((p.y_bottom + p.h) - y) < 1e-9
                )
            ]

            if covered:
                x0 = min(a for a, _ in covered)
                x1 = max(b for _, b in covered)

                members.append(
                    MemberGeometry(
                        f"transom-{y:g}",
                        "transom",
                        x0,
                        y,
                        x1 - x0,
                        "horizontal",
                    )
                )

    return members


def build_geometry(
    window,
    panes=None,
    tenant_id=None,
) -> WindowGeometry:
    """Build the single authoritative geometry graph.

    design_json is authoritative whenever it contains panes. The legacy Pane
    relation is accepted only for older records with no design_json panes.

    IMPORTANT:
    - ``geometry.panes`` remains the logical/design grid.
    - ``geometry.glass`` contains the actual glass boundary.
    """
    design = _parse_design(window)

    design_panes = _design_panes(design)

    if design_panes:
        pane_geoms = design_panes
    else:
        pane_geoms = _legacy_panes(panes or [])

        if not pane_geoms:
            pane_geoms = [
                PaneGeometry(
                    "p1",
                    0.0,
                    0.0,
                    1.0,
                    1.0,
                )
            ]

    profile = load_profile(
        tenant_id,
        getattr(window, "material", "Aluminium"),
        window,
    )

    # design_json['shape'] is the source of truth.
    # Falls back to the legacy window.shape DB column.
    shape = str(
        design.get("shape")
        or getattr(window, "shape", None)
        or "rectangle"
    ).lower()

    if shape == "rectangular":
        shape = "rectangle"

    arch_rise_mm = _number(
        design.get("archRise"),
        0.0,
    )

    if (
        shape in ("arched", "gothic", "circular")
        and arch_rise_mm <= 0
    ):
        arch_rise_mm = float(window.height_mm) * 0.3

    # NEW:
    # Build actual glass geometry from the selected frame shape.
    glass = _glass_geometry(
        pane_geoms,
        shape,
    )

    return WindowGeometry(
        width_mm=float(window.width_mm),
        height_mm=float(window.height_mm),
        profile=profile,
        panes=tuple(pane_geoms),
        glass=tuple(glass),
        members=tuple(_members(pane_geoms)),
        design=design,
        frame_colour_hex=getattr(
            window,
            "frame_colour_hex",
            "#6a6a6c",
        ),
        shape=shape,
        arch_rise_mm=arch_rise_mm,
    )


def pane_namespace(pane: PaneGeometry):
    """Adapter for legacy consumers.

    Values still originate from canonical geometry.
    """
    return SimpleNamespace(
        cell_key=pane.id,
        x_norm=pane.x,
        y_norm=pane.y,
        w_norm=pane.w,
        h_norm=pane.h,
        opener_type=pane.opening,
        glazing_type=pane.glazing,
        infill=pane.infill,
    )


def glass_namespace(glass: GlassGeometry):
    """Adapter for legacy/rendering consumers.

    For circular glass:
        x_norm/y_norm = centre
        radius_x/radius_y = radii
    For rectangular glass:
        x_norm/y_norm/w_norm/h_norm = rectangle bounds.
    """
    return SimpleNamespace(
        id=glass.id,
        shape=glass.shape,
        x_norm=glass.x,
        y_norm=glass.y,
        w_norm=glass.w,
        h_norm=glass.h,
        radius_x=glass.radius_x,
        radius_y=glass.radius_y,
        glazing=glass.glazing,
        infill=glass.infill,
    )


def geometry_summary(geometry: WindowGeometry) -> dict:
    return {
        "width_mm": geometry.width_mm,
        "height_mm": geometry.height_mm,
        "profile": asdict(geometry.profile),
        "shape": geometry.shape,
        "arch_rise_mm": geometry.arch_rise_mm,
        "panes": [
            asdict(p)
            for p in geometry.panes
        ],
        "glass": [
            asdict(g)
            for g in geometry.glass
        ],
        "members": [
            asdict(m)
            for m in geometry.members
        ],
    }