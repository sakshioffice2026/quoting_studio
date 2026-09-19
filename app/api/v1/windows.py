import json

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ...extensions import db
from ...models import Pane
from ...services.domain.pricing import calculate_price
from ...services.domain import project_lock
from ...services.cad.canonical_geometry import assert_legacy_panes_match, sync_legacy_panes
from ._helpers import _own_window

windows_bp = Blueprint('api_v1_windows', __name__)


# GET /api/v1/windows/<id>
@windows_bp.route('/windows/<int:window_id>', methods=['GET'])
@login_required
def get_window(window_id):
    try:
        window = _own_window(window_id)
        current_app.logger.debug('API get_window: id=%d', window_id)
        return jsonify(window.to_dict())
    except Exception as exc:
        current_app.logger.exception('API get_window error id=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to load window'}), 500


# POST /api/v1/windows/<id>/panes
@windows_bp.route('/windows/<int:window_id>/panes', methods=['POST'])
@login_required
def save_panes(window_id):
    try:
        window = _own_window(window_id)
        lock_reason = project_lock.get_lock_reason(current_user.tenant_id, window.project_id)
        if lock_reason:
            return jsonify({'error': lock_reason, 'locked': True}), 409
        data   = request.get_json(force=True)

        if not data:
            current_app.logger.warning('save_panes: empty payload window_id=%d', window_id)
            return jsonify({'error': 'Empty request body'}), 400

        if 'width'          in data: window.width_mm          = int(data['width'])
        if 'height'         in data: window.height_mm         = int(data['height'])
        if 'shape'          in data: window.shape             = data['shape']
        if 'material'       in data: window.material          = data['material']
        if 'frameColor'     in data: window.frame_colour_hex  = data['frameColor']
        if 'frameColorName' in data: window.frame_colour_name = data['frameColorName']

        cells = data.get('cells', [])
        if not isinstance(cells, list):
            return jsonify({'error': 'cells must be an array'}), 400

        design = data.get('design_json')
        if design is None:
            design = json.dumps({'panes': cells})
        elif isinstance(design, dict):
            design = json.dumps(design)
        window.design_json = design
        sync_legacy_panes(window, Pane, db)

        db.session.commit()
        current_app.logger.info('save_panes: window=%d cells=%d', window_id, len(cells))
        return jsonify({'status': 'ok', 'cells_saved': len(cells)})

    except ValueError as exc:
        db.session.rollback()
        current_app.logger.warning('save_panes bad data window=%d: %s', window_id, exc)
        return jsonify({'error': f'Invalid data: {exc}'}), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_panes error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save panes'}), 500


# POST /api/v1/windows/<id>/price
@windows_bp.route('/windows/<int:window_id>/price', methods=['POST'])
@login_required
def get_price(window_id):
    try:
        window = _own_window(window_id)
        data   = request.get_json(force=True) or {}

        class _P:
            def __init__(self, opener, glazing, w=1.0, h=1.0):
                self.opener_type  = opener
                self.glazing_type = glazing
                self.w_norm       = w
                self.h_norm       = h

        cells = data.get('cells', None)
        if cells is not None:
            panes = [_P(c.get('opener', 'Fixed light'), c.get('glazing', 'Double, Low-E'),
                        float(c.get('w', 1.0)), float(c.get('h', 1.0)))
                     for c in cells]
        else:
            panes = window.panes.all()

        if 'material' in data: window.material  = data['material']
        if 'width'    in data: window.width_mm  = int(data['width'])
        if 'height'   in data: window.height_mm = int(data['height'])

        design = data.get('design') or None
        if design is None and (data.get('hardware') or data.get('extras') or data.get('glazingBars') is not None):
            design = {
                'hardware': data.get('hardware', {}),
                'extras':   data.get('extras', {}),
                'panes':    [{'glazingBars': c.get('glazingBars', [])} for c in (cells or [])],
            }
        result = calculate_price(window, panes, current_user.tenant_id, design=design)
        current_app.logger.debug('price: window=%d total=%.2f', window_id, result['total'])
        return jsonify(result)

    except Exception as exc:
        current_app.logger.exception('get_price error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Pricing calculation failed'}), 500


# POST /api/v1/windows/<id>/design
@windows_bp.route('/windows/<int:window_id>/design', methods=['POST'])
@login_required
def save_design(window_id):
    try:
        window = _own_window(window_id)
        lock_reason = project_lock.get_lock_reason(current_user.tenant_id, window.project_id)
        if lock_reason:
            return jsonify({'error': lock_reason, 'locked': True}), 409
        data   = request.get_json(force=True) or {}

        design = data.get('design_json')
        if isinstance(design, str):
            try:
                design_obj = json.loads(design)
            except ValueError as exc:
                return jsonify({'error': f'Invalid design_json: {exc}'}), 400
        elif isinstance(design, dict):
            design_obj = dict(design)
        else:
            design_obj = {}

        if 'cells' in data:
            design_obj['panes'] = data['cells']
        window.design_json = json.dumps(design_obj)

        if 'width'    in data: window.width_mm  = int(data['width'])
        if 'height'   in data: window.height_mm = int(data['height'])
        if 'material' in data: window.material  = data['material']

        shape_val = design_obj.get('shape')
        if shape_val:
            window.shape = str(shape_val)
        if 'frameColor'     in data: window.frame_colour_hex  = data['frameColor']
        if 'frameColorName' in data: window.frame_colour_name = data['frameColorName']
        if 'profileSystemId' in data:
            val = data['profileSystemId']
            window.profile_system_id = int(val) if val else None

        sync_legacy_panes(window, Pane, db)
        db.session.commit()
        current_app.logger.info('Design saved: window=%d panes=%d',
                                 window_id, len(design_obj.get('panes') or []))
        return jsonify({'ok': True, 'window_id': window_id})

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_design error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Design save failed'}), 500
