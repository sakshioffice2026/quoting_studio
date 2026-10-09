import os
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import Window
from ...services.window_overlay_png import render_overlay_png
from ._helpers import _own_window
from .visualisation import _latest_visualisation, _new_version

btl_compose_bp = Blueprint('api_v1_btl_compose', __name__)

CORNER_KEYS = ('tl', 'tr', 'br', 'bl')
OPTION_LIMITS = {
    'shadow':     (0.0, 2.0),
    'reflection': (0.0, 2.0),
    'grain':      (0.0, 2.0),
}


def _clean_options(raw):
    raw = raw if isinstance(raw, dict) else {}
    options = {}
    for key, (low, high) in OPTION_LIMITS.items():
        if key in raw:
            try:
                options[key] = min(high, max(low, float(raw[key])))
            except (TypeError, ValueError):
                pass
    if 'match_colour' in raw:
        options['match_colour'] = bool(raw['match_colour'])
    return options


def _default_strength():
    try:
        return float(os.environ.get('BTL_ENHANCE_STRENGTH', '0.35'))
    except ValueError:
        return 0.35


def _corners_from(vis):
    values = (
        vis.corner_tl_x, vis.corner_tl_y, vis.corner_tr_x, vis.corner_tr_y,
        vis.corner_br_x, vis.corner_br_y, vis.corner_bl_x, vis.corner_bl_y,
    )
    if any(v is None for v in values):
        return None
    return {
        'tl': (vis.corner_tl_x, vis.corner_tl_y),
        'tr': (vis.corner_tr_x, vis.corner_tr_y),
        'br': (vis.corner_br_x, vis.corner_br_y),
        'bl': (vis.corner_bl_x, vis.corner_bl_y),
    }


def _save_png_atomic(cv2, image, full_path):
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    tmp_path = full_path[:-4] + f'.{uuid.uuid4().hex[:6]}.tmp.png'
    if not cv2.imwrite(tmp_path, image):
        return False
    os.replace(tmp_path, full_path)
    return True


# POST /api/v1/windows/<id>/btl/compose
@btl_compose_bp.route('/windows/<int:window_id>/btl/compose', methods=['POST'])
@login_required
def btl_compose(window_id):
    try:
        window = _own_window(window_id)
        data = request.get_json(silent=True) or {}

        vis = _latest_visualisation(window_id)
        if vis is None or not vis.photo_path:
            return jsonify({'error': 'Upload a photo first'}), 400

        corners = _corners_from(vis)
        if corners is None:
            return jsonify({'error': 'Place the four corners first'}), 400

        px = data.get('corners_px')
        if isinstance(px, dict):
            try:
                corners = {k: (float(px[k][0]), float(px[k][1])) for k in CORNER_KEYS}
            except (KeyError, IndexError, TypeError, ValueError):
                pass

        photo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vis.photo_path)
        if not os.path.isfile(photo_path):
            return jsonify({'error': 'Photo file not found'}), 404

        try:
            import cv2
            from ...services.btl import enhancer, limits, pipeline
        except ImportError:
            return jsonify({'error': 'Image processing libraries are not installed'}), 501

        options = _clean_options(data.get('options'))
        use_sam = bool(data.get('use_sam', True))
        use_lama = bool(data.get('use_lama', True))
        tenant_id = current_user.tenant_id

        try:
            strength = min(0.6, max(0.1, float(data.get('enhance_strength', _default_strength()))))
        except (TypeError, ValueError):
            strength = _default_strength()

        enhance_note = None
        enhance_req = bool(data.get('enhance'))
        if enhance_req and not enhancer.is_configured():
            enhance_req = False
            enhance_note = 'Enhance service is not configured'
        if enhance_req:
            allowed, used, cap = limits.within_cap(tenant_id, True)
            if not allowed:
                enhance_req = False
                enhance_note = f'Daily enhance limit reached ({used}/{cap})'

        layer_specs = []
        raw_openings = data.get('openings_px')
        if isinstance(raw_openings, list):
            for item in raw_openings[:12]:
                if not isinstance(item, dict):
                    continue
                try:
                    c = {k: (float(item['corners'][k][0]), float(item['corners'][k][1]))
                         for k in CORNER_KEYS}
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                try:
                    design_id = int(item.get('design_window_id'))
                except (TypeError, ValueError):
                    design_id = None
                src_window = window
                if design_id and design_id != window_id:
                    src_window = Window.query.filter_by(
                        id=design_id, tenant_id=current_user.tenant_id).first() or window
                layer_specs.append((src_window, c))
        if not layer_specs:
            layer_specs = [(window, corners)]

        overlay_cache = {}
        layers = []
        for src_window, c in layer_specs:
            if src_window.id not in overlay_cache:
                overlay_cache[src_window.id] = render_overlay_png(
                    src_window.design_json, src_window.width_mm, src_window.height_mm)
            layers.append((overlay_cache[src_window.id], c))

        overlay = b''.join(png for png, _c in layers)
        key_options = dict(options)
        key_options['_layers'] = [
            [round(c[k][0], 1), round(c[k][1], 1)] for _png, c in layers for k in CORNER_KEYS
        ]

        def key_for(enhance_flag):
            return limits.cache_key(photo_path, overlay, corners, key_options,
                                    enhance_flag, strength, use_sam, use_lama)

        rel_cpu = limits.cache_relpath(key_for(False), False)
        rel_enh = limits.cache_relpath(key_for(True), True) if enhance_req else None

        cached = False
        enhanced = False
        rel_path = None

        if rel_enh and os.path.isfile(limits.cache_fullpath(rel_enh)):
            rel_path, cached, enhanced = rel_enh, True, True
        elif not enhance_req and os.path.isfile(limits.cache_fullpath(rel_cpu)):
            rel_path, cached = rel_cpu, True

        if rel_path is None:
            allowed, used, cap = limits.within_cap(tenant_id, False)
            if not allowed:
                return jsonify({
                    'error': f'Daily render limit reached ({used}/{cap})',
                    'used': used, 'cap': cap,
                }), 429

            result = pipeline.run_layers(photo_path, layers, options=options,
                                        use_sam=use_sam, use_lama=use_lama)
            rel_path = rel_cpu

            if enhance_req:
                try:
                    for _png, layer_corners in layers:
                        result = enhancer.enhance(
                            result,
                            [layer_corners[k] for k in CORNER_KEYS],
                            strength=strength,
                        )
                    enhanced = True
                    rel_path = rel_enh
                except enhancer.EnhanceError as exc:
                    enhance_note = str(exc)
                    current_app.logger.warning('btl enhance fallback window=%d: %s', window_id, exc)

            if not _save_png_atomic(cv2, result, limits.cache_fullpath(rel_path)):
                return jsonify({'error': 'Failed to write render'}), 500

        if cached and vis.rendered_path == rel_path:
            new_vis = vis
        else:
            new_vis = _new_version(window_id, vis)
            new_vis.rendered_path = rel_path
            db.session.commit()

        return jsonify({
            'status':       'ok',
            'vis_id':       new_vis.id,
            'render_url':   f'/uploads/{rel_path}',
            'cached':       cached,
            'enhanced':     enhanced,
            'enhance_note': enhance_note,
        })
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('btl_compose error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Bring to Life render failed'}), 500
