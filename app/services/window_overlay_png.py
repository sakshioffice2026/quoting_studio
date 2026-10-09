import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .domain.design_render_service import _parse, _hex, _num, _rgb, _outline

SUPERSAMPLE = 2
GLASS_RGBA = (214, 232, 244, 110)
PANEL_RGBA = (232, 228, 218, 255)
DEFAULT_HANDLE = '#C9CED3'


def _polygon_mask(size, points):
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def _lighten(colour, amount):
    return tuple(int(v + (255 - v) * amount) for v in colour)


def _darken(colour, amount):
    return tuple(int(v * (1.0 - amount)) for v in colour)


def _shift_mask(mask, dx, dy):
    return mask.transform(
        mask.size, Image.Transform.AFFINE, (1, 0, -dx, 0, 1, -dy),
        resample=Image.Resampling.NEAREST, fillcolor=0)


def _tinted_layer(size, rgb, mask, strength):
    layer = Image.new('RGBA', size, rgb + (0,))
    layer.putalpha(mask.point(lambda p: int(p * strength)))
    return layer


def _bevel_frame(canvas, frame_mask, bar, size):
    """Lit rim on the light-facing frame edges, shaded rim on the opposite edges."""
    d = max(2, int(round(bar * 0.07)))
    soft = ImageFilter.GaussianBlur(max(1, d // 2))

    lit = ImageChops.subtract(frame_mask, _shift_mask(frame_mask, d, d)).filter(soft)
    dark = ImageChops.subtract(frame_mask, _shift_mask(frame_mask, -d, -d)).filter(soft)

    # keep the shading strictly on the frame so the glass transparency is untouched
    lit = ImageChops.multiply(lit, frame_mask)
    dark = ImageChops.multiply(dark, frame_mask)

    canvas = Image.alpha_composite(canvas, _tinted_layer(size, (255, 255, 255), lit, 0.30))
    canvas = Image.alpha_composite(canvas, _tinted_layer(size, (0, 0, 0), dark, 0.38))
    return canvas


def _draw_sash_edges(ddraw, box, sash_w, sash_colour, thickness):
    x0, y0, x1, y1 = box
    lit = _lighten(sash_colour, 0.35) + (255,)
    dark = _darken(sash_colour, 0.35) + (255,)

    ddraw.line([(x0, y0), (x1, y0)], fill=lit, width=thickness)
    ddraw.line([(x0, y0), (x0, y1)], fill=lit, width=thickness)
    ddraw.line([(x0, y1), (x1, y1)], fill=dark, width=thickness)
    ddraw.line([(x1, y0), (x1, y1)], fill=dark, width=thickness)

    i = sash_w
    if (x1 - x0) > 2 * i + 4 and (y1 - y0) > 2 * i + 4:
        ddraw.line([(x0 + i, y0 + i), (x1 - i, y0 + i)], fill=dark, width=thickness)
        ddraw.line([(x0 + i, y0 + i), (x0 + i, y1 - i)], fill=dark, width=thickness)
        ddraw.line([(x0 + i, y1 - i), (x1 - i, y1 - i)], fill=lit, width=thickness)
        ddraw.line([(x1 - i, y0 + i), (x1 - i, y1 - i)], fill=lit, width=thickness)


def _draw_glazing_bar(ddraw, p0, p1, vertical, bar_w, sash_colour, thickness):
    lit = _lighten(sash_colour, 0.35) + (255,)
    dark = _darken(sash_colour, 0.35) + (255,)
    ddraw.line([p0, p1], fill=sash_colour + (255,), width=bar_w)

    half = bar_w / 2.0
    if vertical:
        ddraw.line([(p0[0] - half, p0[1]), (p1[0] - half, p1[1])], fill=lit, width=thickness)
        ddraw.line([(p0[0] + half, p0[1]), (p1[0] + half, p1[1])], fill=dark, width=thickness)
    else:
        ddraw.line([(p0[0], p0[1] - half), (p1[0], p1[1] - half)], fill=lit, width=thickness)
        ddraw.line([(p0[0], p0[1] + half), (p1[0], p1[1] + half)], fill=dark, width=thickness)


def _draw_handle(ddraw, box, opening, sash_w, handle_rgb):
    o = (opening or '').strip().lower()
    if not o or o.startswith('fixed'):
        return

    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    if ph < 6 * sash_w or pw < 4 * sash_w:
        return

    hinge_right = 'right' in o and 'left' not in o
    cx = (x0 + sash_w * 0.5) if hinge_right else (x1 - sash_w * 0.5)
    cy = y0 + ph * 0.5

    plate_w = sash_w * 0.80
    plate_l = sash_w * 1.90
    lever_w = max(sash_w * 0.34, 3.0)
    lever_l = sash_w * 3.2

    plate = handle_rgb + (255,)
    lever = _darken(handle_rgb, 0.12) + (255,)
    shine = _lighten(handle_rgb, 0.45) + (255,)

    ddraw.rounded_rectangle(
        [cx - plate_w / 2, cy - plate_l / 2, cx + plate_w / 2, cy + plate_l / 2],
        radius=plate_w / 2, fill=plate)
    ddraw.rounded_rectangle(
        [cx - lever_w / 2, cy - lever_w / 2, cx + lever_w / 2, cy + lever_l],
        radius=lever_w / 2, fill=lever)
    ddraw.line([(cx - lever_w / 4, cy), (cx - lever_w / 4, cy + lever_l * 0.9)],
               fill=shine, width=max(1, int(lever_w * 0.18)))


def render_overlay_png(design, width_mm, height_mm, max_px=1600):
    design = _parse(design)
    frame = design.get('frame') or {}
    shape = str(design.get('shape') or 'rectangle').lower()

    colour = _rgb(_hex(frame.get('color'), '#2B2F33'))
    sash_colour = _rgb(_hex(frame.get('sashColor'), _hex(frame.get('color'), '#2B2F33')))
    handle_rgb = _rgb(_hex(frame.get('handleColor'), DEFAULT_HANDLE))
    bar_mm = _num(frame.get('thickness'), 58.0)
    rise_mm = _num(design.get('archRise'), 400.0)

    width_mm = max(float(width_mm or 1200), 1.0)
    height_mm = max(float(height_mm or 1400), 1.0)

    px_per_mm = float(max_px) / max(width_mm, height_mm)
    out_w = max(2, round(width_mm * px_per_mm))
    out_h = max(2, round(height_mm * px_per_mm))

    s = SUPERSAMPLE
    w, h = out_w * s, out_h * s
    bar = max(bar_mm * px_per_mm * s, 6.0 * s)
    rise = rise_mm * px_per_mm * s
    size = (w, h)

    canvas = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    outer_pts = _outline(shape, 0, 0, w, h, rise)
    draw.polygon(outer_pts, fill=colour + (255,))

    ix, iy = bar, bar
    iw, ih = max(w - 2 * bar, 2), max(h - 2 * bar, 2)
    inner_pts = _outline(shape, ix, iy, iw, ih, max(rise - bar, 4))
    inner_mask = _polygon_mask(size, inner_pts)
    outer_mask = _polygon_mask(size, outer_pts)
    frame_mask = ImageChops.subtract(outer_mask, inner_mask)

    canvas = _bevel_frame(canvas, frame_mask, bar, size)

    glass = Image.new('RGBA', size, GLASS_RGBA)
    canvas.paste(glass, (0, 0), inner_mask)

    details = Image.new('RGBA', size, (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(details)

    sash_w = max(int(round(bar * 0.45)), 3 * s)
    bar_w = max(int(round(bar * 0.28)), 2 * s)
    edge_t = max(1, s)

    # glazing bead: dark step where the frame meets the glass
    bead_w = max(2, int(round(bar * 0.06)))
    ddraw.line(list(inner_pts) + [inner_pts[0]], fill=_darken(colour, 0.45) + (255,),
               width=bead_w, joint='curve')

    panes = design.get('panes') or design.get('cells') or []
    if not panes:
        panes = [{'x': 0, 'y': 0, 'w': 1, 'h': 1}]

    for pane in panes:
        if not isinstance(pane, dict):
            continue
        try:
            px = ix + float(pane.get('x', 0)) * iw
            py = iy + float(pane.get('y', 0)) * ih
            pw = float(pane.get('w', 1)) * iw
            ph = float(pane.get('h', 1)) * ih
        except (TypeError, ValueError):
            continue
        if pw < 2 or ph < 2:
            continue

        infill = str(pane.get('infill') or 'glass').lower()
        box = [px, py, px + pw, py + ph]
        if infill not in ('glass', ''):
            ddraw.rectangle(box, fill=PANEL_RGBA)
        ddraw.rectangle(box, outline=sash_colour + (255,), width=sash_w)
        _draw_sash_edges(ddraw, box, sash_w, sash_colour, edge_t)

        for bar_def in (pane.get('glazingBars') or []):
            if not isinstance(bar_def, dict):
                continue
            try:
                pos = float(bar_def.get('pos', bar_def.get('position', 0.5)))
            except (TypeError, ValueError):
                continue
            axis = str(bar_def.get('axis', bar_def.get('dir', 'v'))).lower()
            if axis.startswith('h'):
                gy = py + pos * ph
                _draw_glazing_bar(ddraw, (px, gy), (px + pw, gy), False, bar_w, sash_colour, edge_t)
            else:
                gx = px + pos * pw
                _draw_glazing_bar(ddraw, (gx, py), (gx, py + ph), True, bar_w, sash_colour, edge_t)

        opening = str(pane.get('opening') or pane.get('opener') or 'Fixed')
        _draw_handle(ddraw, box, opening, sash_w, handle_rgb)

    clipped_alpha = ImageChops.multiply(details.split()[3], inner_mask)
    details.putalpha(clipped_alpha)
    canvas = Image.alpha_composite(canvas, details)

    result = canvas.resize((out_w, out_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    result.save(buf, 'PNG', optimize=True)
    return buf.getvalue()
