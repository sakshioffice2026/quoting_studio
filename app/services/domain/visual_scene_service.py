import copy
import json
import os
import re
import uuid
from decimal import Decimal

from flask import current_app

from ...extensions import db
from ...models import Project, Window
from ...models.quotation import Quotation
from ...models.visual_scene import (
    GLASS_TINTS, VisualScene, VisualSceneOpening,
)
from .design_render_service import (
    _finish_spec, _frame_hex, _hex, _num, _opening_marks, _shape_path,
    _svg_glass_overlay, _svg_sheen_gradient, _svg_textured_filter,
    _svg_wood_filter,
)
from .pricing import calculate_price

ALLOWED_PHOTO_EXT = {'jpg', 'jpeg', 'png', 'webp'}
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_OPENINGS = 24
MAX_BARS = 8
GLASS_ALPHA_DEFAULT = 0.55
_HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')

FRAME_COLOUR_NAMES = {
    '#2B2F33': 'Anthracite',
    '#E8E4DA': 'White',
    '#7C8AA0': 'Slate',
    '#5C4733': 'Bronze',
    '#1B2430': 'Midnight',
    '#4A6741': 'Sage',
}


# ------------------------------------------------------------------ #
#  Scene lookup / creation
# ------------------------------------------------------------------ #

def _own_project(tenant_id: int, project_id: int) -> Project:
    project = Project.query.filter_by(id=project_id, tenant_id=tenant_id).first()
    if project is None:
        raise LookupError('Project not found')
    return project


def get_scene(tenant_id: int, project_id: int):
    _own_project(tenant_id, project_id)
    return (VisualScene.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(VisualScene.id.desc())
            .first())


def get_or_create_scene(tenant_id: int, project_id: int) -> VisualScene:
    scene = get_scene(tenant_id, project_id)
    if scene is None:
        scene = VisualScene(tenant_id=tenant_id, project_id=project_id)
        db.session.add(scene)
        db.session.commit()
    return scene


# ------------------------------------------------------------------ #
#  Photo
# ------------------------------------------------------------------ #

def save_photo(scene: VisualScene, file_storage) -> VisualScene:
    if file_storage is None or not file_storage.filename:
        raise ValueError('No photo provided')

    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_PHOTO_EXT:
        raise ValueError('Photo must be JPG, PNG or WEBP')

    raw = file_storage.read()
    if not raw:
        raise ValueError('Empty photo')
    if len(raw) > MAX_PHOTO_BYTES:
        raise ValueError('Photo exceeds 15 MB')

    from io import BytesIO
    from PIL import Image
    try:
        img = Image.open(BytesIO(raw))
        img.verify()
        img = Image.open(BytesIO(raw))
        width, height = img.size
    except Exception:
        raise ValueError('File is not a valid image')

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'scenes')
    os.makedirs(folder, exist_ok=True)
    filename = f'scene-{scene.id}-{uuid.uuid4().hex[:10]}.{ext}'
    with open(os.path.join(folder, filename), 'wb') as fh:
        fh.write(raw)

    scene.photo_path = f'scenes/{filename}'
    scene.photo_width = width
    scene.photo_height = height
    scene.version = (scene.version or 1) + 1
    db.session.commit()
    return scene


def save_composite(scene: VisualScene, png_bytes: bytes) -> VisualScene:
    if not png_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Composite must be a PNG image')
    if len(png_bytes) > MAX_PHOTO_BYTES:
        raise ValueError('Composite exceeds 15 MB')

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'scenes')
    os.makedirs(folder, exist_ok=True)
    filename = f'scene-{scene.id}-composite-v{scene.version or 1}.png'
    with open(os.path.join(folder, filename), 'wb') as fh:
        fh.write(png_bytes)

    scene.rendered_path = f'scenes/{filename}'
    db.session.commit()
    return scene


# ------------------------------------------------------------------ #
#  Openings
# ------------------------------------------------------------------ #

def _clean_corners(raw) -> dict:
    out = {}
    for key in ('tl', 'tr', 'bl', 'br'):
        pt = (raw or {}).get(key)
        if isinstance(pt, dict):
            x, y = pt.get('x'), pt.get('y')
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            x, y = pt[0], pt[1]
        else:
            raise ValueError(f'Corner {key} missing')
        out[key] = {'x': _num(x, 0.0), 'y': _num(y, 0.0)}
    return out


def save_openings(scene: VisualScene, tenant_id: int, raw_openings) -> list:
    if not isinstance(raw_openings, list):
        raise ValueError('openings must be a list')

    valid_ids = {
        w.id for w in Window.query.filter_by(
            tenant_id=tenant_id, project_id=scene.project_id).all()
    }

    VisualSceneOpening.query.filter_by(scene_id=scene.id).delete()

    saved = []
    for index, item in enumerate(raw_openings[:MAX_OPENINGS]):
        if not isinstance(item, dict):
            continue
        try:
            window_id = int(item.get('window_id'))
        except (TypeError, ValueError):
            continue
        if window_id not in valid_ids:
            continue
        try:
            corners = _clean_corners(item.get('corners'))
        except ValueError:
            continue

        tint = str(item.get('glass_tint') or 'clear')
        if tint not in GLASS_TINTS:
            tint = 'clear'

        row = VisualSceneOpening(
            scene_id=scene.id,
            window_id=window_id,
            opacity=min(1.0, max(0.1, _num(item.get('opacity'), 0.92))),
            brightness=min(1.6, max(0.4, _num(item.get('brightness'), 1.0))),
            glass_tint=tint,
            z_index=index,
        )
        row.corners = corners
        db.session.add(row)
        saved.append(row)

    scene.version = (scene.version or 1) + 1
    db.session.commit()
    return saved


# ------------------------------------------------------------------ #
#  Options -> design
# ------------------------------------------------------------------ #

def _load_design(window: Window) -> dict:
    design = None
    if getattr(window, 'design_json', None):
        try:
            design = json.loads(window.design_json)
        except (ValueError, TypeError):
            design = None
    if not isinstance(design, dict) or not design:
        design = {
            'shape': 'rectangle',
            'unitType': 'window',
            'frame': {'thickness': 68, 'color': window.frame_colour_hex},
            'panes': [{'id': 'p1', 'x': 0, 'y': 0, 'w': 1, 'h': 1,
                       'opening': 'Fixed', 'infill': 'glass',
                       'glazingBars': []}],
        }
    design['width'] = window.width_mm or design.get('width') or 1200
    design['height'] = window.height_mm or design.get('height') or 1400
    return design


def _even_bars(count: int, axis: str) -> list:
    count = max(0, min(MAX_BARS, int(count)))
    return [{'axis': axis, 'pos': round((i + 1) / (count + 1), 4)}
            for i in range(count)]


def apply_options(design: dict, options: dict) -> dict:
    """Return a copy of design with the option overrides applied."""
    out = copy.deepcopy(design)
    options = options or {}
    frame = out.setdefault('frame', {})

    colour = options.get('frame_color')
    if isinstance(colour, str) and _HEX_RE.match(colour):
        frame['color'] = colour.upper()
        frame['sashColor'] = colour.upper()
        # a woodgrain foil would hide the chosen colour; painted / textured /
        # metallic finishes keep the colour and stay as they are
        if str(frame.get('finish') or '').strip().lower() == 'wood':
            frame['finish'] = ''

    bars = options.get('bars')
    if isinstance(bars, dict):
        v = int(_num(bars.get('v'), 0))
        h = int(_num(bars.get('h'), 0))
        generated = _even_bars(v, 'v') + _even_bars(h, 'h')
        panes = out.get('panes') or out.get('cells') or []
        for pane in panes:
            if isinstance(pane, dict) and \
                    str(pane.get('infill') or 'glass').lower() in ('glass', ''):
                pane['glazingBars'] = copy.deepcopy(generated)
    return out


# ------------------------------------------------------------------ #
#  Overlay SVG (clean, no dimension lines / margins)
# ------------------------------------------------------------------ #

def render_overlay_svg(design: dict, width_mm: float, height_mm: float,
                       uid: str, glass_tint: str = 'clear',
                       glass_alpha: float = GLASS_ALPHA_DEFAULT) -> str:
    frame = design.get('frame') or {}
    shape = str(design.get('shape') or 'rectangle').lower()
    finish = _finish_spec(frame)
    colour = _frame_hex(frame)
    sash = colour if (finish and finish['kind'] == 'wood') else _hex(frame.get('sashColor'), colour)
    bar_mm = _num(frame.get('thickness'), 58.0)
    rise_mm = _num(design.get('archRise'), 400.0)
    tint = GLASS_TINTS.get(glass_tint, GLASS_TINTS['clear'])
    alpha = min(1.0, max(0.1, float(glass_alpha)))

    scale = 1000.0 / max(width_mm, height_mm)
    W, H = width_mm * scale, height_mm * scale
    bar = max(bar_mm * scale, 5.0)
    rise = rise_mm * scale

    parts = []
    extra_defs = []
    clip_id = f'ov-{uid}'

    if shape == 'circular':
        cx, cy = W / 2, H / 2
        inner = (f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
                 f'rx="{max(W / 2 - bar, 1):.1f}" ry="{max(H / 2 - bar, 1):.1f}"/>')
    else:
        inner = (f'<path d="{_shape_path(shape, bar, bar, W - 2 * bar, H - 2 * bar, max(rise - bar, 4))}"/>')

    def shape_el(fill, extra=''):
        if shape == 'circular':
            return (f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{W / 2:.1f}" '
                    f'ry="{H / 2:.1f}" fill="{fill}" {extra}/>')
        return f'<path d="{_shape_path(shape, 0, 0, W, H, rise)}" fill="{fill}" {extra}/>'

    if finish is None:
        parts.append(shape_el(colour))
    elif finish['kind'] == 'wood' and shape in ('rectangle', 'rect', ''):
        b = bar
        fh, fv = f'wh-{uid}', f'wv-{uid}'
        sh, sv = f'sh-{uid}', f'sv-{uid}'
        extra_defs.append(_svg_wood_filter(fh, finish['wood'], False, scale))
        extra_defs.append(_svg_wood_filter(fv, finish['wood'], True, scale))
        extra_defs.append(_svg_sheen_gradient(sh, 'h', finish['gloss'], False))
        extra_defs.append(_svg_sheen_gradient(sv, 'v', finish['gloss'], False))
        bars_pts = (
            (f'0,0 {W:.1f},0 {W - b:.1f},{b:.1f} {b:.1f},{b:.1f}', fh, sh),
            (f'0,{H:.1f} {W:.1f},{H:.1f} {W - b:.1f},{H - b:.1f} {b:.1f},{H - b:.1f}', fh, sh),
            (f'0,0 {b:.1f},{b:.1f} {b:.1f},{H - b:.1f} 0,{H:.1f}', fv, sv),
            (f'{W:.1f},0 {W - b:.1f},{b:.1f} {W - b:.1f},{H - b:.1f} {W:.1f},{H:.1f}', fv, sv),
        )
        for pts, filt, sheen in bars_pts:
            parts.append(f'<polygon points="{pts}" fill="#000" filter="url(#{filt})"/>')
            parts.append(f'<polygon points="{pts}" fill="url(#{sheen})"/>')
        for x1, y1, x2, y2 in (
            (0, 0, b, b), (W, 0, W - b, b), (0, H, b, H - b), (W, H, W - b, H - b),
        ):
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="#000000" stroke-opacity="0.38" stroke-width="1.6"/>')
    else:
        if finish['kind'] == 'wood':
            fid = f'wh-{uid}'
            extra_defs.append(_svg_wood_filter(fid, finish['wood'], False, scale))
            parts.append(shape_el('#000', f'filter="url(#{fid})"'))
        elif finish['kind'] == 'textured':
            fid = f'tx-{uid}'
            extra_defs.append(_svg_textured_filter(fid))
            parts.append(shape_el(colour, f'filter="url(#{fid})"'))
        else:
            parts.append(shape_el(colour))
        gid = f'sd-{uid}'
        extra_defs.append(_svg_sheen_gradient(gid, 'd', finish['gloss'], finish['kind'] == 'metallic'))
        parts.append(shape_el(f'url(#{gid})'))

    ix, iy = bar, bar
    iw, ih = W - 2 * bar, H - 2 * bar

    parts.append(f'<defs><clipPath id="{clip_id}">{inner}</clipPath></defs>')
    parts.append(f'<g clip-path="url(#{clip_id})">')

    panes = design.get('panes') or design.get('cells') or []
    if not panes:
        panes = [{'x': 0, 'y': 0, 'w': 1, 'h': 1, 'opening': 'Fixed'}]

    for pane_index, pane in enumerate(panes):
        if not isinstance(pane, dict):
            continue
        try:
            px = ix + float(pane.get('x', 0)) * iw
            py = iy + float(pane.get('y', 0)) * ih
            pw = float(pane.get('w', 1)) * iw
            ph = float(pane.get('h', 1)) * ih
        except (TypeError, ValueError):
            continue

        opening = str(pane.get('opening') or pane.get('opener') or 'Fixed')
        infill = str(pane.get('infill') or 'glass').lower()
        is_glass = infill in ('glass', '')

        if is_glass:
            parts.append(
                f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" '
                f'fill="{tint}" fill-opacity="{alpha:.2f}" '
                f'stroke="{sash}" stroke-width="4"/>')
            parts.append(
                f'<polygon points="{px:.1f},{py:.1f} {px + pw * 0.55:.1f},{py:.1f} '
                f'{px:.1f},{py + ph * 0.55:.1f}" fill="#FFFFFF" fill-opacity="0.10"/>')
            parts.append(_svg_glass_overlay(uid, pane_index, pane.get('texture'),
                                            px, py, pw, ph, extra_defs))
        else:
            parts.append(
                f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" '
                f'fill="{sash}" stroke="{sash}" stroke-width="4"/>')

        if opening.lower() != 'fixed':
            parts.append(
                f'<rect x="{px + 6:.1f}" y="{py + 6:.1f}" width="{max(pw - 12, 1):.1f}" '
                f'height="{max(ph - 12, 1):.1f}" fill="none" stroke="{sash}" '
                f'stroke-width="2" opacity="0.8"/>')
        parts.append(_opening_marks(px, py, pw, ph, opening))

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
                parts.append(f'<line x1="{px:.1f}" y1="{gy:.1f}" x2="{px + pw:.1f}" '
                             f'y2="{gy:.1f}" stroke="{sash}" stroke-width="5"/>')
            else:
                gx = px + pos * pw
                parts.append(f'<line x1="{gx:.1f}" y1="{py:.1f}" x2="{gx:.1f}" '
                             f'y2="{py + ph:.1f}" stroke="{sash}" stroke-width="5"/>')

    parts.append('</g>')

    defs_markup = f'<defs>{"".join(extra_defs)}</defs>' if extra_defs else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
            f'width="{W:.0f}" height="{H:.0f}" preserveAspectRatio="none">'
            + defs_markup + ''.join(parts) + '</svg>')


# ------------------------------------------------------------------ #
#  Preview / commit / pricing
# ------------------------------------------------------------------ #

def _price_for(window: Window, design: dict, tenant_id: int) -> dict:
    return calculate_price(window, window.panes.all(), tenant_id, design=design)


def preview_opening(window: Window, tenant_id: int, options: dict) -> dict:
    """Render + price a window with unsaved options. Nothing is persisted."""
    options = options or {}
    design = apply_options(_load_design(window), options)

    tint = str(options.get('glass_tint') or 'clear')
    if tint not in GLASS_TINTS:
        tint = 'clear'

    svg = render_overlay_svg(
        design, float(design['width']), float(design['height']),
        uid=f'w{window.id}', glass_tint=tint,
        glass_alpha=_num(options.get('glass_alpha'), GLASS_ALPHA_DEFAULT),
    )
    price = _price_for(window, design, tenant_id)
    return {
        'window_id': window.id,
        'svg': svg,
        'price': price,
        'unit_total': price['total'],
        'width_mm': design['width'],
        'height_mm': design['height'],
    }


def commit_options(window: Window, tenant_id: int, options: dict) -> dict:
    """Persist frame colour / bars onto the window design."""
    if getattr(window, 'design_locked', False):
        raise PermissionError('Design is locked')

    design = apply_options(_load_design(window), options or {})
    window.design_json = json.dumps(design)

    colour = (design.get('frame') or {}).get('color')
    if isinstance(colour, str) and _HEX_RE.match(colour):
        window.frame_colour_hex = colour.upper()
        window.frame_colour_name = FRAME_COLOUR_NAMES.get(colour.upper(), 'Custom')

    window.design_revision = (window.design_revision or 0) + 1
    db.session.commit()
    return {'window_id': window.id, 'design_revision': window.design_revision,
            'price': _price_for(window, design, tenant_id)}


def scene_price_summary(scene: VisualScene, tenant_id: int) -> dict:
    items = []
    subtotal = Decimal('0')
    for opening in scene.openings.all():
        window = opening.window
        if window is None or window.tenant_id != tenant_id:
            continue
        price = _price_for(window, _load_design(window), tenant_id)
        total = Decimal(str(price['total']))
        subtotal += total
        items.append({
            'opening_id': opening.id,
            'window_id': window.id,
            'label': window.label,
            'material': window.material,
            'width_mm': window.width_mm,
            'height_mm': window.height_mm,
            'frame_colour': window.frame_colour_name,
            'glass_tint': opening.glass_tint,
            'frame': price['frame'],
            'hardware': price['hardware'],
            'extras': price['extras'],
            'fitting': price['fitting'],
            'unit_total': price['total'],
        })
    return {'items': items, 'subtotal': float(subtotal)}


def link_quotation(scene: VisualScene, tenant_id: int,
                   quotation_id: int) -> VisualScene:
    quotation = Quotation.query.filter_by(
        id=quotation_id, tenant_id=tenant_id,
        project_id=scene.project_id).first()
    if quotation is None:
        raise LookupError('Quotation not found for this project')
    scene.quotation_id = quotation.id
    db.session.commit()
    return scene
