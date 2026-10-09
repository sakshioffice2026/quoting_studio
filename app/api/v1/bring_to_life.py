import math
import os

from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import login_required
from PIL import Image

from ...extensions import db
from ...models import Visualisation
from ...services.photo_prep import PhotoError, prepare_photo
from ...services.window_overlay_png import render_overlay_png
from ._helpers import _own_window
from .visualisation import _latest_visualisation

btl_bp = Blueprint('api_v1_btl', __name__)

CORNER_KEYS = ('tl', 'tr', 'br', 'bl')
MIN_EDGE_PX = 8.0
OVERSHOOT = 0.5


def _photo_size(vis):
    if vis is None or not vis.photo_path:
        return None
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], vis.photo_path)
    try:
        with Image.open(path) as img:
            return img.size
    except (OSError, ValueError):
        return None


def _parse_corners(raw, photo_size):
    if not isinstance(raw, dict):
        return None, 'corners must be an object'

    pts = {}
    for key in CORNER_KEYS:
        try:
            x, y = float(raw[key][0]), float(raw[key][1])
        except (KeyError, TypeError, ValueError, IndexError):
            return None, f'corner {key} is missing or invalid'
        if not (math.isfinite(x) and math.isfinite(y)):
            return None, f'corner {key} is not a finite number'
        if photo_size:
            pw, ph = photo_size
            if not (-pw * OVERSHOOT <= x <= pw * (1 + OVERSHOOT)
                    and -ph * OVERSHOOT <= y <= ph * (1 + OVERSHOOT)):
                return None, f'corner {key} is far outside the photo'
        pts[key] = (x, y)

    ordered = [pts[k] for k in CORNER_KEYS]
    signs = []
    for i in range(4):
        ax, ay = ordered[i]
        bx, by = ordered[(i + 1) % 4]
        cx, cy = ordered[(i + 2) % 4]
        if math.hypot(bx - ax, by - ay) < MIN_EDGE_PX:
            return None, 'window is too small'
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross == 0:
            return None, 'corners are collinear'
        signs.append(cross > 0)
    if len(set(signs)) != 1:
        return None, 'corners form a twisted or concave shape'

    return pts, None


# POST /api/v1/windows/<id>/btl/photo
@btl_bp.route('/windows/<int:window_id>/btl/photo', methods=['POST'])
@login_required
def btl_upload_photo(window_id):
    try:
        _own_window(window_id)

        file = request.files.get('photo')
        if file is None or file.filename == '':
            return jsonify({'error': 'No photo file in request'}), 400

        photo_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'photos')
        try:
            info = prepare_photo(file.stream, photo_dir, f'window-{window_id}')
        except PhotoError as exc:
            return jsonify({'error': str(exc)}), 400

        vis = _latest_visualisation(window_id)
        if vis is None:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)
        vis.photo_path = f"photos/{info['filename']}"
        db.session.commit()

        return jsonify({
            'status':     'ok',
            'vis_id':     vis.id,
            'photo_url':  f"/uploads/photos/{info['filename']}",
            'width':      info['width'],
            'height':     info['height'],
            'scale':      info['scale'],
        })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('btl_upload_photo error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Photo upload failed'}), 500


# GET /api/v1/windows/<id>/btl/overlay.png
@btl_bp.route('/windows/<int:window_id>/btl/overlay.png', methods=['GET'])
@login_required
def btl_overlay_png(window_id):
    try:
        window = _own_window(window_id)
        try:
            max_px = int(request.args.get('max_px', 1600))
        except (TypeError, ValueError):
            max_px = 1600
        max_px = min(2400, max(200, max_px))

        data = render_overlay_png(window.design_json, window.width_mm, window.height_mm, max_px=max_px)
        resp = Response(data, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    except Exception as exc:
        current_app.logger.exception('btl_overlay_png error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to render overlay'}), 500


# POST /api/v1/windows/<id>/btl/corners
@btl_bp.route('/windows/<int:window_id>/btl/corners', methods=['POST'])
@login_required
def btl_save_corners(window_id):
    try:
        _own_window(window_id)
        data = request.get_json(silent=True) or {}

        vis = _latest_visualisation(window_id)
        pts, error = _parse_corners(data.get('corners'), _photo_size(vis))
        if error:
            return jsonify({'error': error}), 400

        if vis is None:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)

        vis.corner_tl_x, vis.corner_tl_y = pts['tl']
        vis.corner_tr_x, vis.corner_tr_y = pts['tr']
        vis.corner_bl_x, vis.corner_bl_y = pts['bl']
        vis.corner_br_x, vis.corner_br_y = pts['br']
        db.session.commit()

        return jsonify({'status': 'ok', 'vis_id': vis.id})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('btl_save_corners error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save corners'}), 500
