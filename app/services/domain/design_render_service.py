"""
Customer-facing design drawings for a Design Approval.

- build_drawings(approval)  -> list of dicts (label, size, details, inline SVG)
- build_design_pdf(...)     -> PDF bytes (WeasyPrint) with the same drawings

Drawings are rendered from approval.design_snapshot_json, i.e. the design as it
was when it was submitted, never from the live editor.
"""
from __future__ import annotations

import html
import io
import json
import logging
import math
import re
import textwrap

from flask import render_template_string
from markupsafe import Markup

from ...models.window import Window

logger = logging.getLogger(__name__)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

HANDLE_LABELS = {
    "lever": "Lever",
    "monkeytail": "Monkey tail",
    "tbar": "T-bar",
    "cockspur": "Cockspur",
    "knob": "Knob",
}

DOOR_LABELS = {
    "single": "Single door",
    "double": "Double door",
    "sl": "Single door + side light (left)",
    "sr": "Single door + side light (right)",
    "fanlight": "Single door + fanlight",
    "fullset": "Full set (door + side lights + fanlight)",
}


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def _hex(value, default: str) -> str:
    if isinstance(value, str) and _HEX_RE.match(value):
        return value
    return default


def _num(value, default: float) -> float:
    try:
        number = float(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _parse(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


# ------------------------------------------------------------------ #
#  SVG
# ------------------------------------------------------------------ #

def _opening_marks(x: float, y: float, w: float, h: float, opening: str) -> str:
    """Dashed opening-direction symbol for one pane."""
    o = (opening or "").lower()
    style = 'fill="none" stroke="#1B2430" stroke-width="1.4" stroke-dasharray="7 5" opacity="0.7"'

    if "slid" in o:
        cy = y + h / 2
        x1, x2 = x + w * 0.25, x + w * 0.75
        return (
            f'<line x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}" '
            f'stroke="#1B2430" stroke-width="2" opacity="0.7"/>'
            f'<polygon points="{x2:.1f},{cy:.1f} {x2 - 10:.1f},{cy - 5:.1f} {x2 - 10:.1f},{cy + 5:.1f}" '
            f'fill="#1B2430" opacity="0.7"/>'
        )

    if "left" in o:
        ax, ay = x, y + h / 2
        return f'<polyline points="{x + w:.1f},{y:.1f} {ax:.1f},{ay:.1f} {x + w:.1f},{y + h:.1f}" {style}/>'

    if "right" in o:
        ax, ay = x + w, y + h / 2
        return f'<polyline points="{x:.1f},{y:.1f} {ax:.1f},{ay:.1f} {x:.1f},{y + h:.1f}" {style}/>'

    if "tilt" in o or "bottom" in o:
        ax, ay = x + w / 2, y + h
        return f'<polyline points="{x:.1f},{y:.1f} {ax:.1f},{ay:.1f} {x + w:.1f},{y:.1f}" {style}/>'

    if "top" in o:
        ax, ay = x + w / 2, y
        return f'<polyline points="{x:.1f},{y + h:.1f} {ax:.1f},{ay:.1f} {x + w:.1f},{y + h:.1f}" {style}/>'

    return ""


def _shape_path(shape: str, x: float, y: float, w: float, h: float, rise: float) -> str:
    """Outline path for rectangle / arched / gothic. Circular is handled separately."""
    if shape in ("arched", "arch"):
        rise = min(rise, h * 0.8, w / 2)
        return (
            f"M {x:.1f},{y + h:.1f} L {x:.1f},{y + rise:.1f} "
            f"Q {x + w / 2:.1f},{y - rise:.1f} {x + w:.1f},{y + rise:.1f} "
            f"L {x + w:.1f},{y + h:.1f} Z"
        )
    if shape == "gothic":
        rise = min(rise, h * 0.8)
        return (
            f"M {x:.1f},{y + h:.1f} L {x:.1f},{y + rise:.1f} "
            f"Q {x + w * 0.12:.1f},{y + rise * 0.45:.1f} {x + w / 2:.1f},{y:.1f} "
            f"Q {x + w * 0.88:.1f},{y + rise * 0.45:.1f} {x + w:.1f},{y + rise:.1f} "
            f"L {x + w:.1f},{y + h:.1f} Z"
        )
    return f"M {x:.1f},{y:.1f} L {x + w:.1f},{y:.1f} L {x + w:.1f},{y + h:.1f} L {x:.1f},{y + h:.1f} Z"


def render_svg(design: dict, width_mm: float, height_mm: float, uid: str) -> str:
    """Returns an inline <svg> string for one window/door."""
    frame = design.get("frame") or {}
    shape = str(design.get("shape") or "rectangle").lower()
    colour = _hex(frame.get("color"), "#2B2F33")
    sash_colour = _hex(frame.get("sashColor"), colour)
    bar_mm = _num(frame.get("thickness"), 58.0)
    rise_mm = _num(design.get("archRise"), 400.0)
    has_cill = bool(frame.get("cill"))

    max_w, max_h = 520.0, 640.0
    scale = min(max_w / width_mm, max_h / height_mm)
    W, H = width_mm * scale, height_mm * scale
    bar = max(bar_mm * scale, 5.0)
    rise = rise_mm * scale

    margin_l, margin_t, margin_r, margin_b = 20.0, 46.0, 62.0, 24.0
    ox, oy = margin_l, margin_t
    vb_w = W + margin_l + margin_r
    vb_h = H + margin_t + margin_b + (10 if has_cill else 0)

    parts: list[str] = []

    # Outer frame + inner opening
    clip_id = f"clip-{uid}"
    if shape == "circular":
        cx, cy = ox + W / 2, oy + H / 2
        parts.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{W / 2:.1f}" ry="{H / 2:.1f}" fill="{colour}"/>')
        irx, iry = max(W / 2 - bar, 1), max(H / 2 - bar, 1)
        inner_shape = f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{irx:.1f}" ry="{iry:.1f}"/>'
    else:
        parts.append(f'<path d="{_shape_path(shape, ox, oy, W, H, rise)}" fill="{colour}"/>')
        inner_shape = (
            f'<path d="{_shape_path(shape, ox + bar, oy + bar, W - 2 * bar, H - 2 * bar, max(rise - bar, 4))}"/>'
        )

    ix, iy = ox + bar, oy + bar
    iw, ih = W - 2 * bar, H - 2 * bar

    parts.append(f'<defs><clipPath id="{clip_id}">{inner_shape}</clipPath></defs>')
    parts.append(f'<g clip-path="url(#{clip_id})">')
    parts.append(f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iw:.1f}" height="{ih:.1f}" fill="#DCEBF5"/>')

    panes = design.get("panes") or design.get("cells") or []
    if not panes:
        panes = [{"x": 0, "y": 0, "w": 1, "h": 1, "opening": "Fixed"}]

    for pane in panes:
        if not isinstance(pane, dict):
            continue
        try:
            px = ix + float(pane.get("x", 0)) * iw
            py = iy + float(pane.get("y", 0)) * ih
            pw = float(pane.get("w", 1)) * iw
            ph = float(pane.get("h", 1)) * ih
        except (TypeError, ValueError):
            continue

        opening = str(pane.get("opening") or pane.get("opener") or "Fixed")
        infill = str(pane.get("infill") or "glass").lower()
        fill = "#E8E4DA" if infill not in ("glass", "") else "#DCEBF5"

        parts.append(
            f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" '
            f'fill="{fill}" stroke="{sash_colour}" stroke-width="3"/>'
        )
        if opening.lower() != "fixed":
            parts.append(
                f'<rect x="{px + 4:.1f}" y="{py + 4:.1f}" width="{max(pw - 8, 1):.1f}" height="{max(ph - 8, 1):.1f}" '
                f'fill="none" stroke="{sash_colour}" stroke-width="1.5" opacity="0.8"/>'
            )
        parts.append(_opening_marks(px, py, pw, ph, opening))

        for bar_def in (pane.get("glazingBars") or []):
            if not isinstance(bar_def, dict):
                continue
            try:
                pos = float(bar_def.get("pos", bar_def.get("position", 0.5)))
            except (TypeError, ValueError):
                continue
            if str(bar_def.get("axis", bar_def.get("dir", "v"))).lower().startswith("h"):
                gy = py + pos * ph
                parts.append(f'<line x1="{px:.1f}" y1="{gy:.1f}" x2="{px + pw:.1f}" y2="{gy:.1f}" stroke="{sash_colour}" stroke-width="2"/>')
            else:
                gx = px + pos * pw
                parts.append(f'<line x1="{gx:.1f}" y1="{py:.1f}" x2="{gx:.1f}" y2="{py + ph:.1f}" stroke="{sash_colour}" stroke-width="2"/>')

    parts.append("</g>")

    if has_cill:
        parts.append(
            f'<rect x="{ox - 8:.1f}" y="{oy + H:.1f}" width="{W + 16:.1f}" height="8" '
            f'fill="{colour}" opacity="0.9"/>'
        )

    # Dimension lines
    dim = "#1D4ED8"
    top_y = oy - 16
    parts.append(
        f'<line x1="{ox:.1f}" y1="{top_y:.1f}" x2="{ox + W:.1f}" y2="{top_y:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<line x1="{ox:.1f}" y1="{top_y - 5:.1f}" x2="{ox:.1f}" y2="{top_y + 5:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<line x1="{ox + W:.1f}" y1="{top_y - 5:.1f}" x2="{ox + W:.1f}" y2="{top_y + 5:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<text x="{ox + W / 2:.1f}" y="{top_y - 6:.1f}" text-anchor="middle" font-size="13" '
        f'font-family="Arial, sans-serif" font-weight="700" fill="{dim}">{int(round(width_mm))} mm</text>'
    )
    right_x = ox + W + 18
    parts.append(
        f'<line x1="{right_x:.1f}" y1="{oy:.1f}" x2="{right_x:.1f}" y2="{oy + H:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<line x1="{right_x - 5:.1f}" y1="{oy:.1f}" x2="{right_x + 5:.1f}" y2="{oy:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<line x1="{right_x - 5:.1f}" y1="{oy + H:.1f}" x2="{right_x + 5:.1f}" y2="{oy + H:.1f}" stroke="{dim}" stroke-width="1.2"/>'
        f'<text x="{right_x + 16:.1f}" y="{oy + H / 2:.1f}" text-anchor="middle" font-size="13" '
        f'font-family="Arial, sans-serif" font-weight="700" fill="{dim}" '
        f'transform="rotate(90 {right_x + 16:.1f} {oy + H / 2:.1f})">{int(round(height_mm))} mm</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.0f} {vb_h:.0f}" '
        f'width="100%" role="img" aria-label="Design drawing" style="max-height:640px;">'
        + "".join(parts)
        + "</svg>"
    )


# ------------------------------------------------------------------ #
#  Drawings for an approval
# ------------------------------------------------------------------ #

def _details(window, design: dict, width_mm: float, height_mm: float) -> list[tuple[str, str]]:
    frame = design.get("frame") or {}
    door = design.get("door") or {}
    panes = design.get("panes") or design.get("cells") or []

    rows: list[tuple[str, str]] = [("Size", f"{int(round(width_mm))} × {int(round(height_mm))} mm")]

    material = frame.get("material") or (window.material if window else None)
    if material:
        rows.append(("Material", str(material)))

    colour_name = frame.get("colorName") or (window.frame_colour_name if window else None)
    ral = frame.get("ral") or (window.ral_code if window else "")
    if colour_name:
        rows.append(("Frame colour", f"{colour_name}" + (f" ({ral})" if ral else "")))

    if str(design.get("unitType") or "").lower() == "door":
        dtype = str(door.get("dtype") or "single").lower()
        rows.append(("Door type", DOOR_LABELS.get(dtype, dtype.title())))

    handle_type = str(frame.get("handleType") or "").lower()
    if handle_type:
        handle = HANDLE_LABELS.get(handle_type, handle_type.title())
        handle_colour = str(frame.get("handleColor") or "").title()
        rows.append(("Handle", f"{handle}" + (f", {handle_colour}" if handle_colour else "")))

    glazing = sorted({str(p.get("glazing") or p.get("glazingType") or "") for p in panes if isinstance(p, dict)} - {""})
    if glazing:
        rows.append(("Glazing", " / ".join(glazing)))

    openings = [str(p.get("opening") or p.get("opener") or "Fixed") for p in panes if isinstance(p, dict)]
    if openings:
        rows.append(("Panes", f"{len(openings)} — " + ", ".join(openings)))

    return rows


def build_drawings(approval) -> list[dict]:
    """One entry per window/door in the approval snapshot."""
    snapshot = approval.snapshot or {}
    ids = []
    for key in snapshot.keys():
        try:
            ids.append(int(key))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []

    windows = (
        Window.query
        .filter(Window.tenant_id == approval.tenant_id, Window.id.in_(ids))
        .order_by(Window.sequence_order, Window.id)
        .all()
    )

    drawings: list[dict] = []
    for index, window in enumerate(windows, start=1):
        design = _parse(snapshot.get(str(window.id)))
        width_mm = _num(design.get("width"), float(window.width_mm or 1200))
        height_mm = _num(design.get("height"), float(window.height_mm or 1400))

        try:
            svg = render_svg(design, width_mm, height_mm, uid=f"{approval.id}-{window.id}")
        except Exception as exc:  # never break the public page for one bad drawing
            logger.exception("design drawing failed window=%s: %s", window.id, exc)
            svg = ""

        drawings.append(
            {
                "index": index,
                "window_id": window.id,
                "label": window.label or f"Unit {index}",
                "svg": Markup(svg),
                "design": design,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "details": _details(window, design, width_mm, height_mm),
            }
        )
    return drawings


# ------------------------------------------------------------------ #
#  PDF
# ------------------------------------------------------------------ #

_PDF_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {
    size: A4;
    margin: 16mm 14mm 18mm 14mm;
    @bottom-center {
      content: "Design revision {{ approval.revision_number }} · Page " counter(page) " of " counter(pages);
      font-family: Arial, sans-serif; font-size: 8.5pt; color: #8A93A6;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #1B2430; line-height: 1.45; }
  .head { border-bottom: 2.5pt solid #C97B3D; padding-bottom: 8pt; margin-bottom: 14pt; }
  .company { font-size: 16pt; font-weight: 700; }
  .title { font-size: 12pt; margin-top: 4pt; }
  .meta { font-size: 9pt; color: #6B7280; margin-top: 3pt; }
  .unit { page-break-inside: avoid; margin-bottom: 16pt; border: 1pt solid #E5E7EB; border-radius: 4pt; padding: 10pt; }
  .unit h2 { font-size: 11.5pt; margin-bottom: 8pt; }
  .unit .art { text-align: center; }
  .unit .art svg { width: 62%; max-height: 105mm; }
  table { width: 100%; border-collapse: collapse; margin-top: 8pt; font-size: 9.5pt; }
  td { padding: 3pt 4pt; border-bottom: 0.5pt solid #F0F0F0; vertical-align: top; }
  td.k { width: 30%; color: #6B7280; }
  .note { font-size: 8.5pt; color: #6B7280; margin-top: 10pt; }
</style>
</head>
<body>
  <div class="head">
    <div class="company">{{ tenant.name if tenant and tenant.name else 'FenestraOne' }}</div>
    <div class="title">Design for approval — {{ project.display_name if project and project.display_name else 'Project' }}</div>
    <div class="meta">
      Design revision {{ approval.revision_number }}
      {% if approval.sent_at %} · Sent {{ approval.sent_at.strftime('%d %b %Y') }}{% endif %}
      {% if approval.expires_at %} · Respond by {{ approval.expires_at.strftime('%d %b %Y') }}{% endif %}
    </div>
  </div>

  {% for d in drawings %}
  <div class="unit">
    <h2>{{ d.index }}. {{ d.label }}</h2>
    <div class="art">{{ d.svg }}</div>
    <table>
      {% for k, v in d.details %}
      <tr><td class="k">{{ k }}</td><td>{{ v }}</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endfor %}

  <div class="note">
    Drawings are illustrative and not to scale for fine detail. Dimensions shown are in millimetres.
    Dashed lines show the opening direction of each sash.
  </div>
</body>
</html>
"""


# ------------------------------------------------------------------ #
#  PDF fallback (Pillow) — used when WeasyPrint's native libraries
#  (GTK / Pango) are not installed, e.g. on a plain Windows machine.
# ------------------------------------------------------------------ #

_PAGE_W, _PAGE_H = 1240, 1754   # A4 at 150 dpi
_INK = (27, 36, 48)
_MUTED = (107, 114, 128)
_DIM = (29, 78, 216)
_WEASY_OK: bool | None = None


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    names = (
        ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
        if bold
        else ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _text(draw, xy, value, font, fill, anchor=None):
    try:
        if anchor:
            draw.text(xy, value, font=font, fill=fill, anchor=anchor)
        else:
            draw.text(xy, value, font=font, fill=fill)
    except ValueError:
        draw.text(xy, value, font=font, fill=fill)


def _rgb(value: str) -> tuple:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _quad(p0, c, p1, steps: int = 28) -> list:
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        a, b, d = (1 - t) ** 2, 2 * (1 - t) * t, t ** 2
        pts.append((a * p0[0] + b * c[0] + d * p1[0], a * p0[1] + b * c[1] + d * p1[1]))
    return pts


def _outline(shape: str, x: float, y: float, w: float, h: float, rise: float) -> list:
    if shape == "circular":
        cx, cy = x + w / 2, y + h / 2
        return [
            (cx + (w / 2) * math.cos(2 * math.pi * i / 96), cy + (h / 2) * math.sin(2 * math.pi * i / 96))
            for i in range(96)
        ]
    if shape in ("arched", "arch"):
        rise = min(rise, h * 0.8, w / 2)
        pts = [(x, y + h), (x, y + rise)]
        pts += _quad((x, y + rise), (x + w / 2, y - rise), (x + w, y + rise))
        pts.append((x + w, y + h))
        return pts
    if shape == "gothic":
        rise = min(rise, h * 0.8)
        pts = [(x, y + h), (x, y + rise)]
        pts += _quad((x, y + rise), (x + w * 0.12, y + rise * 0.45), (x + w / 2, y))
        pts += _quad((x + w / 2, y), (x + w * 0.88, y + rise * 0.45), (x + w, y + rise))
        pts.append((x + w, y + h))
        return pts
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _dashed(draw, p0, p1, fill, width: int = 3, dash: float = 14, gap: float = 9) -> None:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        draw.line(
            [(p0[0] + ux * pos, p0[1] + uy * pos), (p0[0] + ux * end, p0[1] + uy * end)],
            fill=fill, width=width,
        )
        pos += dash + gap


def _pil_marks(draw, px: float, py: float, pw: float, ph: float, opening: str) -> None:
    o = (opening or "").lower()
    if "slid" in o:
        cy = py + ph / 2
        x1, x2 = px + pw * 0.25, px + pw * 0.75
        draw.line([(x1, cy), (x2, cy)], fill=_INK, width=4)
        draw.polygon([(x2, cy), (x2 - 20, cy - 10), (x2 - 20, cy + 10)], fill=_INK)
        return
    if "left" in o:
        pts = [(px + pw, py), (px, py + ph / 2), (px + pw, py + ph)]
    elif "right" in o:
        pts = [(px, py), (px + pw, py + ph / 2), (px, py + ph)]
    elif "tilt" in o or "bottom" in o:
        pts = [(px, py), (px + pw / 2, py + ph), (px + pw, py)]
    elif "top" in o:
        pts = [(px, py + ph), (px + pw / 2, py), (px + pw, py + ph)]
    else:
        return
    for a, b in zip(pts, pts[1:]):
        _dashed(draw, a, b, _INK, 3)


def _draw_unit(page, design: dict, width_mm: float, height_mm: float, box: tuple) -> None:
    from PIL import Image, ImageDraw

    bx, by, bw, bh = box
    frame = design.get("frame") or {}
    shape = str(design.get("shape") or "rectangle").lower()
    frame_hex = _hex(frame.get("color"), "#2B2F33")
    colour = _rgb(frame_hex)
    sash = _rgb(_hex(frame.get("sashColor"), frame_hex))
    bar_mm = _num(frame.get("thickness"), 58.0)
    rise_mm = _num(design.get("archRise"), 400.0)
    has_cill = bool(frame.get("cill"))

    pad_top, pad_right = 70.0, 150.0
    scale = min(
        (bw - pad_right - 20) / width_mm,
        (bh - pad_top - 20 - (16 if has_cill else 0)) / height_mm,
    )
    W, H = width_mm * scale, height_mm * scale
    bar = max(bar_mm * scale, 8.0)
    rise = rise_mm * scale
    ox = bx + (bw - pad_right - W) / 2
    oy = by + pad_top

    draw = ImageDraw.Draw(page)
    draw.polygon(_outline(shape, ox, oy, W, H, rise), fill=colour)

    ix, iy, iw, ih = ox + bar, oy + bar, W - 2 * bar, H - 2 * bar
    inner = _outline(shape, ix, iy, iw, ih, max(rise - bar, 6))

    layer = Image.new("RGB", page.size, (220, 235, 245))
    ld = ImageDraw.Draw(layer)

    panes = design.get("panes") or design.get("cells") or []
    if not panes:
        panes = [{"x": 0, "y": 0, "w": 1, "h": 1, "opening": "Fixed"}]

    for pane in panes:
        if not isinstance(pane, dict):
            continue
        try:
            px = ix + float(pane.get("x", 0)) * iw
            py = iy + float(pane.get("y", 0)) * ih
            pw = float(pane.get("w", 1)) * iw
            ph = float(pane.get("h", 1)) * ih
        except (TypeError, ValueError):
            continue

        opening = str(pane.get("opening") or pane.get("opener") or "Fixed")
        infill = str(pane.get("infill") or "glass").lower()
        fill = (220, 235, 245) if infill in ("glass", "") else (232, 228, 218)

        ld.rectangle([px, py, px + pw, py + ph], fill=fill, outline=sash, width=5)
        if opening.lower() != "fixed":
            ld.rectangle([px + 7, py + 7, px + pw - 7, py + ph - 7], outline=sash, width=2)
        _pil_marks(ld, px, py, pw, ph, opening)

        for bar_def in (pane.get("glazingBars") or []):
            if not isinstance(bar_def, dict):
                continue
            try:
                pos = float(bar_def.get("pos", bar_def.get("position", 0.5)))
            except (TypeError, ValueError):
                continue
            if str(bar_def.get("axis", bar_def.get("dir", "v"))).lower().startswith("h"):
                gy = py + pos * ph
                ld.line([(px, gy), (px + pw, gy)], fill=sash, width=3)
            else:
                gx = px + pos * pw
                ld.line([(gx, py), (gx, py + ph)], fill=sash, width=3)

    mask = Image.new("L", page.size, 0)
    ImageDraw.Draw(mask).polygon(inner, fill=255)
    page.paste(layer, (0, 0), mask)

    if has_cill:
        draw.rectangle([ox - 14, oy + H, ox + W + 14, oy + H + 14], fill=colour)

    # dimension lines
    f_dim = _font(26, bold=True)
    ty = oy - 30
    draw.line([(ox, ty), (ox + W, ty)], fill=_DIM, width=3)
    draw.line([(ox, ty - 9), (ox, ty + 9)], fill=_DIM, width=3)
    draw.line([(ox + W, ty - 9), (ox + W, ty + 9)], fill=_DIM, width=3)
    _text(draw, (ox + W / 2, ty - 16), f"{int(round(width_mm))} mm", f_dim, _DIM, anchor="mm")

    rx = ox + W + 36
    draw.line([(rx, oy), (rx, oy + H)], fill=_DIM, width=3)
    draw.line([(rx - 9, oy), (rx + 9, oy)], fill=_DIM, width=3)
    draw.line([(rx - 9, oy + H), (rx + 9, oy + H)], fill=_DIM, width=3)
    _text(draw, (rx + 16, oy + H / 2), f"{int(round(height_mm))} mm", f_dim, _DIM, anchor="lm")


def _build_pdf_pillow(approval, project, tenant, drawings: list) -> bytes:
    from PIL import Image, ImageDraw

    company = tenant.name if tenant and getattr(tenant, "name", None) else "FenestraOne"
    project_name = (
        project.display_name if project and getattr(project, "display_name", None) else "Project"
    )
    meta = f"Design revision {approval.revision_number}"
    if approval.sent_at:
        meta += " · Sent " + approval.sent_at.strftime("%d %b %Y")
    if approval.expires_at:
        meta += " · Respond by " + approval.expires_at.strftime("%d %b %Y")

    f_title, f_head = _font(46, bold=True), _font(34, bold=True)
    f_text, f_small = _font(28), _font(22)

    items = drawings or [None]
    pages = []

    for item in items:
        page = Image.new("RGB", (_PAGE_W, _PAGE_H), "white")
        d = ImageDraw.Draw(page)

        _text(d, (70, 60), company, f_title, _INK)
        _text(d, (70, 125), f"Design for approval — {project_name}", f_head, _INK)
        _text(d, (70, 178), meta, f_small, _MUTED)
        d.line([(70, 218), (_PAGE_W - 70, 218)], fill=(201, 123, 61), width=5)

        if item is None:
            _text(d, (70, 270), "No drawings are available for this design.", f_text, _MUTED)
        else:
            _text(d, (70, 248), f"{item['index']}. {item['label']}", f_head, _INK)
            _draw_unit(
                page, item["design"], item["width_mm"], item["height_mm"],
                (70, 305, _PAGE_W - 140, 840),
            )
            y = 1170
            for key, value in item["details"]:
                _text(d, (70, y), str(key), f_text, _MUTED)
                lines = textwrap.wrap(str(value), 52) or [""]
                for line in lines:
                    _text(d, (390, y), line, f_text, _INK)
                    y += 40
                y += 8

        _text(
            d, (70, _PAGE_H - 90),
            "Drawings are illustrative. Dimensions are in millimetres. "
            "Dashed lines show the opening direction.",
            f_small, _MUTED,
        )
        pages.append(page)

    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return buf.getvalue()


def build_design_pdf(approval, project, tenant, drawings: list[dict] | None = None) -> bytes:
    global _WEASY_OK

    drawings = drawings if drawings is not None else build_drawings(approval)

    if _WEASY_OK is None:
        try:
            from weasyprint import HTML  # noqa: F401
            _WEASY_OK = True
        except Exception as exc:  # OSError when GTK/Pango libraries are missing
            logger.warning("WeasyPrint unavailable (%s); using Pillow PDF fallback", exc)
            _WEASY_OK = False

    if not _WEASY_OK:
        return _build_pdf_pillow(approval, project, tenant, drawings)

    from weasyprint import HTML

    markup = render_template_string(
        _PDF_TEMPLATE,
        approval=approval,
        project=project,
        tenant=tenant,
        drawings=drawings,
    )
    return HTML(string=markup).write_pdf()
