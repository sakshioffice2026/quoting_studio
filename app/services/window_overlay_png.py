import io
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .domain.design_render_service import _parse, _hex, _num, _rgb, _outline

SUPERSAMPLE = 2
GLASS_RGBA = (214, 232, 244, 110)
PANEL_RGBA = (232, 228, 218, 255)
DEFAULT_HANDLE = '#C9CED3'

# ---------------------------------------------------------------------------
#  Finishes
# ---------------------------------------------------------------------------
# key -> (kind, gloss 0..1)
FINISHES = {
    'painted_smooth': ('paint', 0.35),
    'painted_satin': ('paint', 0.18),
    'painted_matt': ('paint', 0.05),
    'textured': ('textured', 0.04),
    'wood': ('wood', 0.10),
    'metallic': ('metallic', 0.60),
}

# key -> (base, dark, light, seed)
WOODS = {
    'golden_oak': ('#B07A3B', '#7E4F22', '#D29C57', 3),
    'natural_oak': ('#C79A5E', '#946A35', '#E2BC82', 5),
    'light_oak': ('#D8B787', '#B08A55', '#EBD3AA', 8),
    'dark_oak': ('#6B4423', '#3F2512', '#8D6238', 13),
    'walnut': ('#5A3A24', '#321D10', '#7A5337', 21),
    'rosewood': ('#6E2F25', '#3E160F', '#924638', 34),
    'mahogany': ('#5B2A1F', '#331510', '#7C3D2C', 55),
    'teak': ('#A06A3A', '#6F4520', '#C38E58', 89),
    'cherry': ('#8A4A32', '#5C2D1B', '#AE6A4A', 144),
    'black_ash': ('#2A2522', '#120F0D', '#443C37', 233),
    'grey_oak': ('#8A8379', '#5C564E', '#B0A89B', 377),
}

TILE_W, TILE_H = 1024, 256
TILE_MM_PER_PX = 90.0 / TILE_H      # one tile is about 360 mm along x 90 mm across

_RAW_TILES = {}
_SCALED_TILES = {}
_SPECKLE = {}


def _finish_spec(frame):
    key = str(frame.get('finish') or '').strip().lower()
    if key not in FINISHES:
        return None
    kind, gloss = FINISHES[key]
    wood = str(frame.get('wood') or 'natural_oak').strip().lower()
    if wood not in WOODS:
        wood = 'natural_oak'
    return {'kind': kind, 'gloss': gloss, 'wood': wood}


def _noise_layer(rng, cols, rows, size):
    """Smooth noise: random cells enlarged to `size`."""
    raw = Image.frombytes('L', (cols, rows), rng.randbytes(cols * rows))
    return raw.resize(size, Image.Resampling.BICUBIC)


def _make_seamless(img):
    """Blend the image with a half-width shifted copy so it tiles along x."""
    w, h = img.size
    shifted = ImageChops.offset(img, w // 2, 0)
    row = Image.new('L', (w, 1))
    row.putdata([int(255 * (1.0 - abs(2.0 * x / (w - 1) - 1.0))) for x in range(w)])
    mask = row.resize((w, h), Image.Resampling.NEAREST)
    return Image.composite(img, shifted, mask)


def _wood_tile(key):
    """Tileable wood texture, grain running along x."""
    if key in _RAW_TILES:
        return _RAW_TILES[key]

    base, dark, light, seed = WOODS[key]
    rng = random.Random(seed)
    size = (TILE_W, TILE_H)

    grain = _noise_layer(rng, 14, 56, size)       # long grain lines
    rings = _noise_layer(rng, 5, 10, size)        # broad ring variation
    pores = _noise_layer(rng, 300, 90, size)      # fine pores
    fine = _noise_layer(rng, 40, 120, size)       # medium streaks

    grain, rings, pores, fine = [_make_seamless(i) for i in (grain, rings, pores, fine)]

    body = Image.blend(grain, rings, 0.30)
    detail = Image.blend(pores, fine, 0.50)
    value = Image.blend(body, detail, 0.22)
    value = ImageOps.autocontrast(value, cutoff=1)

    tile = ImageOps.colorize(value, black=_rgb(dark), white=_rgb(light), mid=_rgb(base))
    _RAW_TILES[key] = tile
    return tile


def _scaled_tile(key, vertical, ppm):
    factor = max(ppm * TILE_MM_PER_PX, 0.05)
    tw = max(64, int(TILE_W * factor))
    th = max(32, int(TILE_H * factor))
    ck = (key, vertical, tw)
    if ck in _SCALED_TILES:
        return _SCALED_TILES[ck]

    tile = _wood_tile(key).resize((tw, th), Image.Resampling.LANCZOS)
    if vertical:
        tile = tile.transpose(Image.Transpose.ROTATE_90)
    if len(_SCALED_TILES) > 64:
        _SCALED_TILES.clear()
    _SCALED_TILES[ck] = tile
    return tile


def _tile_fill(tile, size, ox=0, oy=0):
    w, h = size
    tw, th = tile.size
    out = Image.new(tile.mode, (w, h))
    y = -(oy % th)
    while y < h:
        x = -(ox % tw)
        while x < w:
            out.paste(tile, (x, y))
            x += tw
        y += th
    return out


def _frame_regions(shape, w, h, bar, frame_mask):
    """(bbox, mask, vertical, ox, oy) for every bar of the frame."""
    b = int(round(bar))
    regions = []
    if b < 1 or 2 * b >= min(w, h):
        return regions

    if shape in ('rectangle', 'rect', ''):
        bars = (
            ((0, 0, w, b), [(0, 0), (w, 0), (w - b, b), (b, b)], False, 0, 0),
            ((0, h - b, w, h), [(0, h), (w, h), (w - b, h - b), (b, h - b)], False, 437, 97),
            ((0, 0, b, h), [(0, 0), (b, b), (b, h - b), (0, h)], True, 0, 0),
            ((w - b, 0, w, h), [(w, 0), (w - b, b), (w - b, h - b), (w, h)], True, 131, 311),
        )
        for bbox, pts, vertical, ox, oy in bars:
            x0, y0, x1, y1 = bbox
            m = Image.new('L', (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(m).polygon([(px - x0, py - y0) for px, py in pts], fill=255)
            m = ImageChops.multiply(m, frame_mask.crop(bbox))
            regions.append((bbox, m, vertical, ox, oy))
        return regions

    strips = (
        ((0, 0, b, h), True, 0, 0),
        ((w - b, 0, w, h), True, 131, 311),
        ((b, 0, w - b, h), False, 0, 0),
    )
    for bbox, vertical, ox, oy in strips:
        regions.append((bbox, frame_mask.crop(bbox), vertical, ox, oy))
    return regions


def _paint_wood(canvas, regions, key, ppm):
    for bbox, mask, vertical, ox, oy in regions:
        size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if size[0] < 1 or size[1] < 1:
            continue
        tex = _tile_fill(_scaled_tile(key, vertical, ppm), size, ox, oy)
        canvas.paste(tex, (bbox[0], bbox[1]), mask)


def _interp(stops, t):
    for i in range(1, len(stops)):
        t0, v0 = stops[i - 1]
        t1, v1 = stops[i]
        if t <= t1:
            span = max(t1 - t0, 1e-6)
            return v0 + (v1 - v0) * ((t - t0) / span)
    return stops[-1][1]


def _sheen_alpha(size, vertical, gloss, metallic):
    """Highlight (white) and shade (black) alpha maps across the bar thickness."""
    w, h = size
    n = max(w if vertical else h, 2)
    spec = min(0.8, gloss * 1.1)
    shade = 0.12 + 0.10 * gloss

    if metallic:
        white_stops = [(0, 0.45), (0.20, 0.10), (0.38, 0.0), (0.55, 0.50), (0.78, 0.0), (1, 0.0)]
        black_stops = [(0, 0.0), (0.20, 0.0), (0.38, 0.18), (0.55, 0.0), (0.78, 0.12), (1, 0.34)]
    else:
        white_stops = [(0, spec * 0.55), (0.28, spec), (0.44, spec * 0.10), (1, 0.0)]
        black_stops = [(0, 0.0), (0.44, 0.0), (0.75, shade * 0.30), (1, shade)]

    def build(stops):
        row = Image.new('L', (n, 1) if vertical else (1, n))
        row.putdata([int(255 * _interp(stops, i / (n - 1))) for i in range(n)])
        return row.resize((w, h), Image.Resampling.BILINEAR)

    return build(white_stops), build(black_stops)


def _paint_sheen(canvas, regions, gloss, metallic):
    for bbox, mask, vertical, _ox, _oy in regions:
        size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if size[0] < 2 or size[1] < 2:
            continue
        white, black = _sheen_alpha(size, vertical, gloss, metallic)
        for rgb, alpha in (((255, 255, 255), white), ((0, 0, 0), black)):
            layer = Image.new('RGBA', size, rgb + (0,))
            layer.putalpha(ImageChops.multiply(alpha, mask))
            canvas.alpha_composite(layer, dest=(bbox[0], bbox[1]))


def _speckle_tiles():
    if _SPECKLE:
        return _SPECKLE
    rng = random.Random(77)
    noise = Image.frombytes('L', (256, 256), rng.randbytes(256 * 256))
    _SPECKLE['dark'] = noise.point(lambda p: min(255, max(0, p - 170) * 3))
    _SPECKLE['light'] = noise.point(lambda p: min(255, max(0, 85 - p) * 3))
    return _SPECKLE


def _paint_speckle(canvas, mask):
    tiles = _speckle_tiles()
    for rgb, key, strength in (((0, 0, 0), 'dark', 0.40), ((255, 255, 255), 'light', 0.30)):
        full = _tile_fill(tiles[key], canvas.size)
        alpha = ImageChops.multiply(full, mask).point(lambda p, k=strength: int(p * k))
        layer = Image.new('RGBA', canvas.size, rgb + (0,))
        layer.putalpha(alpha)
        canvas = Image.alpha_composite(canvas, layer)
    return canvas


def _wood_sash_layer(size, hmask, vmask, key, ppm):
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    for mask, vertical, ox, oy in ((hmask, False, 53, 211), (vmask, True, 91, 17)):
        bbox = mask.getbbox()
        if not bbox:
            continue
        region = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        tex = _tile_fill(_scaled_tile(key, vertical, ppm), region, ox + bbox[0], oy + bbox[1])
        layer.paste(tex, (bbox[0], bbox[1]), mask.crop(bbox))
    return layer


# ---------------------------------------------------------------------------
#  Existing helpers
# ---------------------------------------------------------------------------
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


def _draw_glazing_bar(ddraw, p0, p1, vertical, bar_w, sash_colour, thickness, fill=True):
    lit = _lighten(sash_colour, 0.35) + (255,)
    dark = _darken(sash_colour, 0.35) + (255,)
    if fill:
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


# ---------------------------------------------------------------------------
#  Render
# ---------------------------------------------------------------------------
def render_overlay_png(design, width_mm, height_mm, max_px=1600):
    design = _parse(design)
    frame = design.get('frame') or {}
    shape = str(design.get('shape') or 'rectangle').lower()

    colour = _rgb(_hex(frame.get('color'), '#2B2F33'))
    sash_colour = _rgb(_hex(frame.get('sashColor'), _hex(frame.get('color'), '#2B2F33')))
    handle_rgb = _rgb(_hex(frame.get('handleColor'), DEFAULT_HANDLE))
    bar_mm = _num(frame.get('thickness'), 58.0)
    rise_mm = _num(design.get('archRise'), 400.0)

    finish = _finish_spec(frame)
    is_wood = bool(finish and finish['kind'] == 'wood')
    if is_wood:
        colour = _rgb(WOODS[finish['wood']][0])
        sash_colour = colour
    need_masks = bool(finish and finish['kind'] in ('wood', 'textured'))

    width_mm = max(float(width_mm or 1200), 1.0)
    height_mm = max(float(height_mm or 1400), 1.0)

    px_per_mm = float(max_px) / max(width_mm, height_mm)
    out_w = max(2, round(width_mm * px_per_mm))
    out_h = max(2, round(height_mm * px_per_mm))

    s = SUPERSAMPLE
    w, h = out_w * s, out_h * s
    bar = max(bar_mm * px_per_mm * s, 6.0 * s)
    rise = rise_mm * px_per_mm * s
    ppm = px_per_mm * s
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

    # finish: woodgrain along each bar, then paint / metallic sheen
    if finish:
        regions = _frame_regions(shape, w, h, bar, frame_mask)
        if is_wood:
            _paint_wood(canvas, regions, finish['wood'], ppm)
        _paint_sheen(canvas, regions, finish['gloss'], finish['kind'] == 'metallic')

    canvas = _bevel_frame(canvas, frame_mask, bar, size)

    glass = Image.new('RGBA', size, GLASS_RGBA)
    canvas.paste(glass, (0, 0), inner_mask)

    panels = Image.new('RGBA', size, (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(panels)

    details = Image.new('RGBA', size, (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(details)

    hmask = Image.new('L', size, 0) if need_masks else None
    vmask = Image.new('L', size, 0) if need_masks else None
    hdraw = ImageDraw.Draw(hmask) if need_masks else None
    vdraw = ImageDraw.Draw(vmask) if need_masks else None

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
            pdraw.rectangle(box, fill=PANEL_RGBA)
        if not is_wood:
            ddraw.rectangle(box, outline=sash_colour + (255,), width=sash_w)
        _draw_sash_edges(ddraw, box, sash_w, sash_colour, edge_t)

        if need_masks:
            hdraw.rectangle([px, py, px + pw, py + sash_w], fill=255)
            hdraw.rectangle([px, py + ph - sash_w, px + pw, py + ph], fill=255)
            vdraw.rectangle([px, py + sash_w, px + sash_w, py + ph - sash_w], fill=255)
            vdraw.rectangle([px + pw - sash_w, py + sash_w, px + pw, py + ph - sash_w], fill=255)

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
                _draw_glazing_bar(ddraw, (px, gy), (px + pw, gy), False, bar_w,
                                  sash_colour, edge_t, fill=not is_wood)
                if need_masks:
                    hdraw.rectangle([px, gy - bar_w / 2.0, px + pw, gy + bar_w / 2.0], fill=255)
            else:
                gx = px + pos * pw
                _draw_glazing_bar(ddraw, (gx, py), (gx, py + ph), True, bar_w,
                                  sash_colour, edge_t, fill=not is_wood)
                if need_masks:
                    vdraw.rectangle([gx - bar_w / 2.0, py, gx + bar_w / 2.0, py + ph], fill=255)

        opening = str(pane.get('opening') or pane.get('opener') or 'Fixed')
        _draw_handle(ddraw, box, opening, sash_w, handle_rgb)

    # solid panels first, so sash texture and edges sit on top of them
    panels.putalpha(ImageChops.multiply(panels.split()[3], inner_mask))
    canvas = Image.alpha_composite(canvas, panels)

    sash_mask = None
    if need_masks:
        vmask = ImageChops.subtract(vmask, hmask)
        hmask = ImageChops.multiply(hmask, inner_mask)
        vmask = ImageChops.multiply(vmask, inner_mask)
        sash_mask = ImageChops.lighter(hmask, vmask)

    if is_wood:
        sash_layer = _wood_sash_layer(size, hmask, vmask, finish['wood'], ppm)
        sash_layer.putalpha(ImageChops.multiply(sash_layer.split()[3], sash_mask))
        canvas = Image.alpha_composite(canvas, sash_layer)

    clipped_alpha = ImageChops.multiply(details.split()[3], inner_mask)
    details.putalpha(clipped_alpha)
    canvas = Image.alpha_composite(canvas, details)

    if finish and finish['kind'] == 'textured':
        canvas = _paint_speckle(canvas, ImageChops.lighter(frame_mask, sash_mask))

    result = canvas.resize((out_w, out_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    result.save(buf, 'PNG', optimize=True)
    return buf.getvalue()
