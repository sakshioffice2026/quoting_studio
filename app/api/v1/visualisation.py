import base64
import json
import os
import uuid

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ...extensions import db
from ...models import Visualisation, Window
from ...models.quotation import Quotation, QuotationStatus
from ...services.domain import quotation_service, visual_feedback_service
from ._helpers import _own_window

vis_bp = Blueprint('api_v1_vis', __name__)

MAX_OPENINGS = 12
MAX_RENDER_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
CLOSED_STATUSES = set(QuotationStatus.TERMINAL) | {QuotationStatus.EXPIRED}


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clean_openings(raw):
    """Sanitise the openings list coming from the client."""
    if not isinstance(raw, list):
        return []
    tenant_window_ids = {
        w.id for w in Window.query.filter_by(tenant_id=current_user.tenant_id).all()
    }
    out = []
    for item in raw[:MAX_OPENINGS]:
        if not isinstance(item, dict):
            continue
        c = item.get('corners') or {}
        try:
            corners = {k: [_num(c[k][0]), _num(c[k][1])] for k in ('tl', 'tr', 'bl', 'br')}
        except (KeyError, TypeError, IndexError):
            continue
        design_id = item.get('design_window_id')
        try:
            design_id = int(design_id)
        except (TypeError, ValueError):
            design_id = None
        if design_id not in tenant_window_ids:
            design_id = None
        out.append({
            'id':               str(item.get('id') or uuid.uuid4().hex[:8])[:16],
            'design_window_id': design_id,
            'corners':          corners,
            'opacity':          min(1.0, max(0.1, _num(item.get('opacity'), 0.92))),
            'brightness':       min(1.6, max(0.4, _num(item.get('brightness'), 1.0))),
        })
    return out


def _latest_visualisation(window_id):
    return (Visualisation.query
            .filter_by(window_id=window_id)
            .order_by(Visualisation.created_at.desc(), Visualisation.id.desc())
            .first())


def _new_version(window_id, base):
    """Every saved render is a new Visualisation row (a version) that starts
    from the previous version's photo, corners and overlay settings."""
    vis = Visualisation(window_id=window_id)
    if base is not None:
        vis.photo_path    = base.photo_path
        vis.corner_tl_x   = base.corner_tl_x
        vis.corner_tl_y   = base.corner_tl_y
        vis.corner_tr_x   = base.corner_tr_x
        vis.corner_tr_y   = base.corner_tr_y
        vis.corner_bl_x   = base.corner_bl_x
        vis.corner_bl_y   = base.corner_bl_y
        vis.corner_br_x   = base.corner_br_x
        vis.corner_br_y   = base.corner_br_y
        vis.opacity       = base.opacity
        vis.brightness    = base.brightness
        vis.openings_json = base.openings_json
    db.session.add(vis)
    db.session.flush()
    return vis


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

        if len(img_bytes) > MAX_RENDER_BYTES:
            return jsonify({'error': 'Render image is too large'}), 413
        if not img_bytes.startswith(PNG_SIGNATURE):
            return jsonify({'error': 'Render must be a PNG image'}), 400

        render_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'renders')
        os.makedirs(render_dir, exist_ok=True)

        previous = _latest_visualisation(window_id)
        version  = Visualisation.query.filter_by(window_id=window_id).count() + 1
        filename = f'window-{window_id}-v{version}-{uuid.uuid4().hex[:6]}.png'
        with open(os.path.join(render_dir, filename), 'wb') as f:
            f.write(img_bytes)

        vis = _new_version(window_id, previous)
        vis.rendered_path = f'renders/{filename}'
        db.session.commit()

        current_app.logger.info('save_render: window=%d version=%d saved %d bytes',
                                window_id, version, len(img_bytes))
        return jsonify({
            'status':     'ok',
            'version':    version,
            'vis_id':     vis.id,
            'render_url': f'/uploads/renders/{filename}',
        })

    except Exception as exc:
        db.session.rollback()
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

        vis = _latest_visualisation(window_id)
        if not vis:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)
        vis.photo_path = f'photos/{filename}'
        db.session.commit()

        photo_url = f'/uploads/photos/{filename}'
        current_app.logger.info('upload_photo: window=%d -> %s', window_id, photo_path)
        return jsonify({'status': 'ok', 'photo_url': photo_url, 'vis_id': vis.id})

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('upload_photo error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Photo upload failed'}), 500


# GET /api/v1/windows/<id>/visualisation
@vis_bp.route('/windows/<int:window_id>/visualisation', methods=['GET'])
@login_required
def get_visualisation(window_id):
    try:
        _own_window(window_id)
        vis = _latest_visualisation(window_id)
        if not vis:
            return jsonify({'exists': False})

        render_url = (f'/uploads/{vis.rendered_path}' if vis.rendered_path else None)
        photo_url  = f'/uploads/{vis.photo_path}' if vis.photo_path else None

        return jsonify({
            'exists':     True,
            'id':         vis.id,
            'version':    Visualisation.query.filter_by(window_id=window_id).count(),
            'render_url': render_url,
            'photo_url':  photo_url,
            'opacity':    vis.opacity,
            'brightness': vis.brightness,
            'openings':   vis.openings,
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

        vis = _latest_visualisation(window_id)
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

        if 'opacity'    in data: vis.opacity    = min(1.0, max(0.1, _num(data['opacity'], 0.92)))
        if 'brightness' in data: vis.brightness = min(1.6, max(0.4, _num(data['brightness'], 1.0)))

        if 'openings' in data:
            vis.openings_json = json.dumps(_clean_openings(data['openings']))

        db.session.commit()
        current_app.logger.debug('save_visualisation: window=%d vis=%d', window_id, vis.id)
        return jsonify({'status': 'ok', 'vis_id': vis.id})

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_visualisation error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save visualisation'}), 500


# POST /api/v1/windows/<id>/sync-quotations
# Staff changed colour / glass / hardware / size in the visualiser. The line
# item is rebuilt and priced on the server from the saved window; nothing
# price-related is read from the request. Approvals on changed items reset.
@vis_bp.route('/windows/<int:window_id>/sync-quotations', methods=['POST'])
@login_required
def sync_quotations(window_id):
    try:
        window    = _own_window(window_id)
        tenant_id = current_user.tenant_id

        rebuilt, _ = quotation_service._build_line_items([window], tenant_id)
        if not rebuilt:
            return jsonify({'error': 'Could not price this unit'}), 422
        fresh = rebuilt[0]

        candidates = Quotation.query.filter_by(
            tenant_id=tenant_id, project_id=window.project_id).all()

        results = []
        for q in candidates:
            if q.status in CLOSED_STATUSES:
                continue

            items   = q.line_items
            changed = False
            for index, old in enumerate(items):
                try:
                    if int(old.get('window_id')) != window.id:
                        continue
                except (TypeError, ValueError):
                    continue

                qty = old.get('qty') or 1
                merged = {**old, **fresh}
                merged['qty']    = qty
                merged['label']  = old.get('label') or fresh.get('label')
                merged['amount'] = round(float(fresh.get('unit_total') or 0) * float(qty), 2)
                if 'notes' in old:
                    merged['notes'] = old['notes']
                if merged != old:
                    items[index] = merged
                    changed = True

            if not changed:
                continue

            q.line_items_json = json.dumps(items)
            quotation_service._recompute_totals(q)
            db.session.flush()
            reset = visual_feedback_service.refresh_approvals(
                tenant_id, q.id, commit=False)
            results.append({
                'quotation_id':        q.id,
                'quotation_number':    q.quotation_number,
                'subtotal':            float(q.subtotal or 0),
                'grand_total':         float(q.grand_total or 0),
                'approvals_reset':     reset,
                'open_requests':       visual_feedback_service.open_request_count(tenant_id, q.id),
            })

        db.session.commit()
        return jsonify({
            'status':     'ok',
            'unit_total': float(fresh.get('unit_total') or 0),
            'quotations': results,
        })

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('sync_quotations error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to update quotations'}), 500