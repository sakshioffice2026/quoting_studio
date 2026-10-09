import io

from PIL import Image, ImageChops, ImageDraw

from .domain.design_render_service import _parse, _hex, _num, _rgb, _outline

SUPERSAMPLE = 2
GLASS_RGBA = (214, 232, 244, 110)
PANEL_RGBA = (232, 228, 218, 255)


def _polygon_mask(size, points):
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def render_overlay_png(design, width_mm, height_mm, max_px=1600):
    design = _parse(design)
    frame = design.get('frame') or {}
    shape = str(design.get('shape') or 'rectangle').lower()

    colour = _rgb(_hex(frame.get('color'), '#2B2F33'))
    sash_colour = _rgb(_hex(frame.get('sashColor'), _hex(frame.get('color'), '#2B2F33')))
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

    glass = Image.new('RGBA', size, GLASS_RGBA)
    canvas.paste(glass, (0, 0), inner_mask)

    details = Image.new('RGBA', size, (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(details)

    sash_w = max(int(round(bar * 0.45)), 3 * s)
    bar_w = max(int(round(bar * 0.28)), 2 * s)

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
                ddraw.line([(px, gy), (px + pw, gy)], fill=sash_colour + (255,), width=bar_w)
            else:
                gx = px + pos * pw
                ddraw.line([(gx, py), (gx, py + ph)], fill=sash_colour + (255,), width=bar_w)

    clipped_alpha = ImageChops.multiply(details.split()[3], inner_mask)
    details.putalpha(clipped_alpha)
    canvas = Image.alpha_composite(canvas, details)

    result = canvas.resize((out_w, out_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    result.save(buf, 'PNG', optimize=True)
    return buf.getvalue()
