import base64
import glob
import os
import uuid

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required

from ...extensions import db
from ...models import Visualisation
from ._helpers import _own_window

vis_bp = Blueprint('api_v1_vis', __name__)


# POST /api/v1/windows/<id>/render
@vis_bp.route('/windows/<int:window_id>/render', methods=['POST'])
@login_required
def save_render(window_id):
    try:
        _own_window(window_id)
        data = request.get_json(force=True) or {}
        b64  = data.get('image', '')

        if not b64:
            return jsonify({'error': 'No image data provided'}), 400

        if ',' in b64:
            b64 = b64.split(',', 1)[1]

        try:
            img_bytes = base64.b64decode(b64)
        except Exception as exc:
            current_app.logger.warning('save_render: invalid base64 window=%d: %s', window_id, exc)
            return jsonify({'error': 'Invalid base64 image data'}), 400

        render_dir  = os.path.join(current_app.config['UPLOAD_FOLDER'], 'renders')
        os.makedirs(render_dir, exist_ok=True)
        filename    = f'window-{window_id}.png'
        render_path = os.path.join(render_dir, filename)

        with open(render_path, 'wb') as f:
            f.write(img_bytes)

        render_url = f'/uploads/renders/{filename}'

        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if vis is None:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)
        vis.rendered_path = f'renders/{filename}'
        db.session.commit()

        current_app.logger.info('save_render: window=%d saved %d bytes -> %s',
                                 window_id, len(img_bytes), render_path)
        return jsonify({'status': 'ok', 'render_url': render_url})

    except Exception as exc:
        current_app.logger.exception('save_render error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save render'}), 500


# POST /api/v1/windows/<id>/photo
@vis_bp.route('/windows/<int:window_id>/photo', methods=['POST'])
@login_required
def upload_photo(window_id):
    try:
        _own_window(window_id)

        if 'photo' not in request.files:
            return jsonify({'error': 'No photo file in request'}), 400

        file = request.files['photo']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        allowed = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed:
            return jsonify({'error': f'File type .{ext} not allowed'}), 400

        photo_dir  = os.path.join(current_app.config['UPLOAD_FOLDER'], 'photos')
        os.makedirs(photo_dir, exist_ok=True)
        filename   = f'window-{window_id}-{uuid.uuid4().hex[:8]}.{ext}'
        photo_path = os.path.join(photo_dir, filename)
        file.save(photo_path)

        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if not vis:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)
        vis.photo_path = f'photos/{filename}'
        db.session.commit()

        photo_url = f'/uploads/photos/{filename}'
        current_app.logger.info('upload_photo: window=%d → %s', window_id, photo_path)
        return jsonify({'status': 'ok', 'photo_url': photo_url, 'vis_id': vis.id})

    except Exception as exc:
        current_app.logger.exception('upload_photo error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Photo upload failed'}), 500


# GET /api/v1/windows/<id>/visualisation
@vis_bp.route('/windows/<int:window_id>/visualisation', methods=['GET'])
@login_required
def get_visualisation(window_id):
    try:
        _own_window(window_id)
        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if not vis:
            return jsonify({'exists': False})

        render_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'renders')
        pattern    = os.path.join(render_dir, f'window-{window_id}-*.png')
        matches    = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        render_url = (f'/uploads/renders/{os.path.basename(matches[0])}'
                      if matches else None)
        photo_url  = f'/uploads/{vis.photo_path}' if vis.photo_path else None

        return jsonify({
            'exists':     True,
            'id':         vis.id,
            'render_url': render_url,
            'photo_url':  photo_url,
            'opacity':    vis.opacity,
            'brightness': vis.brightness,
            'corners': {
                'tl': [vis.corner_tl_x, vis.corner_tl_y],
                'tr': [vis.corner_tr_x, vis.corner_tr_y],
                'bl': [vis.corner_bl_x, vis.corner_bl_y],
                'br': [vis.corner_br_x, vis.corner_br_y],
            } if vis.corner_tl_x is not None else None,
        })
    except Exception as exc:
        current_app.logger.exception('get_visualisation error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to load visualisation'}), 500


# POST /api/v1/windows/<id>/visualisation
@vis_bp.route('/windows/<int:window_id>/visualisation', methods=['POST'])
@login_required
def save_visualisation(window_id):
    try:
        _own_window(window_id)
        data = request.get_json(force=True) or {}

        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if not vis:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)

        corners = data.get('corners', {})
        if corners:
            tl = corners.get('tl', [None, None])
            tr = corners.get('tr', [None, None])
            bl = corners.get('bl', [None, None])
            br = corners.get('br', [None, None])
            vis.corner_tl_x = tl[0]; vis.corner_tl_y = tl[1]
            vis.corner_tr_x = tr[0]; vis.corner_tr_y = tr[1]
            vis.corner_bl_x = bl[0]; vis.corner_bl_y = bl[1]
            vis.corner_br_x = br[0]; vis.corner_br_y = br[1]

        if 'opacity'    in data: vis.opacity    = float(data['opacity'])
        if 'brightness' in data: vis.brightness = float(data['brightness'])

        db.session.commit()
        current_app.logger.debug('save_visualisation: window=%d vis=%d', window_id, vis.id)
        return jsonify({'status': 'ok', 'vis_id': vis.id})

    except Exception as exc:
        current_app.logger.exception('save_visualisation error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save visualisation'}), 500
