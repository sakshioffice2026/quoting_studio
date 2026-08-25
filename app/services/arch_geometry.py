"""arch_geometry.py — shared curve math for arched/gothic/circular frame
shapes, used by both the DXF elevation (engineering_dxf.py) and the 3D/STEP
builder (frame_assembly.py / model3d.py) so both stay geometrically
identical instead of the 3D path silently falling back to a rectangle.
"""
from __future__ import annotations

import math

CURVED_SHAPES = ("arched", "gothic", "circular")


def arch_height_mm(W: float, H: float, arch_rise_mm: float | None) -> float:
    return float(arch_rise_mm) if arch_rise_mm and arch_rise_mm > 0 else min(W * 0.25, 400.0)


def _quad_bezier(p0, p1, p2, segments):
    pts = []
    for i in range(segments + 1):
        t = i / segments
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def arched_outline(W: float, H: float, arch_rise_mm: float, inset: float = 0.0, segments: int = 24):
    """Semicircular head. Mirrors engineering_dxf._elevation's 'arched' branch:
    radius = W/2, centre at (W/2, H-arch_height). `inset` pulls the whole
    outline inward by `inset` (used to place a member centreline)."""
    height = arch_height_mm(W, H, arch_rise_mm)
    spring_y = H - height
    cx = W / 2.0
    cy = spring_y
    radius = W / 2.0 - inset
    pts = []
    for i in range(segments + 1):
        t = i / segments
        angle = math.pi - t * math.pi  # 180deg -> 0deg
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts, spring_y


def gothic_outline(W: float, H: float, arch_rise_mm: float, inset: float = 0.0, segments: int = 16):
    """Two-centre pointed head. Mirrors engineering_dxf._elevation's 'gothic'
    branch (two quadratic Beziers, 0.6 control-point factor)."""
    height = arch_height_mm(W, H, arch_rise_mm)
    spring_y = H - height
    apex = (W / 2.0, H - inset)
    ctrl_y = spring_y + 0.6 * height
    left_spring = (0.0 + inset, spring_y)
    left_ctrl = (0.0 + inset, ctrl_y)
    right_spring = (W - inset, spring_y)
    right_ctrl = (W - inset, ctrl_y)
    pts = _quad_bezier(left_spring, left_ctrl, apex, segments)
    pts += _quad_bezier(apex, right_ctrl, right_spring, segments)[1:]
    return pts, spring_y


def circular_outline(W: float, H: float, inset: float = 0.0, segments: int = 48):
    """Full ellipse inscribed in the W x H box. Mirrors engineering_dxf's
    'circular' branch (ellipse fit to the bounding box)."""
    cx, cy = W / 2.0, H / 2.0
    a = max(W / 2.0 - inset, 1.0)
    b = max(H / 2.0 - inset, 1.0)
    pts = []
    for i in range(segments):
        t = 2 * math.pi * i / segments
        pts.append((cx + a * math.cos(t), cy + b * math.sin(t)))
    pts.append(pts[0])
    return pts


def read_shape(window) -> tuple[str, float]:
    """(shape, arch_rise_mm) from design_json, same precedence as
    canonical_geometry.build_geometry / engineering_dxf._elevation."""
    import json

    design = {}
    raw = getattr(window, "design_json", None)
    if isinstance(raw, dict):
        design = raw
    elif raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                design = parsed
        except (TypeError, ValueError):
            design = {}

    shape = str(design.get("shape") or getattr(window, "shape", None) or "rectangle").lower()
    if shape == "rectangular":
        shape = "rectangle"

    arch_rise = design.get("archRise")
    try:
        arch_rise = float(arch_rise) if arch_rise is not None else 0.0
    except (TypeError, ValueError):
        arch_rise = 0.0

    return shape, arch_rise
