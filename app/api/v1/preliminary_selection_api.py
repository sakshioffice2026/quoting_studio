from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ...services.domain import preliminary_selection_service

presel_api_bp = Blueprint('presel_api', __name__)


def _err(exc, code=400):
    return jsonify({'error': str(exc)}), code


@presel_api_bp.route('/preliminary-selections', methods=['GET'])
@login_required
def list_preselections():
    status = request.args.get('status') or None
    items = preliminary_selection_service.list_preselections(current_user.tenant_id, status=status)
    return jsonify([p.to_dict() for p in items])


@presel_api_bp.route('/preliminary-selections/<int:presel_id>', methods=['GET'])
@login_required
def get_preselection(presel_id):
    presel = preliminary_selection_service.get_preselection(current_user.tenant_id, presel_id)
    if not presel:
        return jsonify({'error': 'Preliminary selection not found'}), 404
    return jsonify(presel.to_dict())


@presel_api_bp.route('/leads/<int:lead_id>/preliminary-selection', methods=['GET'])
@login_required
def get_preselection_by_lead(lead_id):
    presel = preliminary_selection_service.get_by_lead(current_user.tenant_id, lead_id)
    if not presel:
        return jsonify({'error': 'Preliminary selection not found'}), 404
    return jsonify(presel.to_dict())


@presel_api_bp.route('/leads/<int:lead_id>/preliminary-selection', methods=['POST'])
@login_required
def start_preliminary_selection(lead_id):
    data = request.get_json(force=True) or {}
    try:
        presel = preliminary_selection_service.start_preliminary_selection(
            tenant_id=current_user.tenant_id,
            lead_id=lead_id,
            created_by=current_user.id,
            shortlisted_ranges=data.get('shortlisted_ranges'),
            rough_opening_doors=data.get('rough_opening_doors'),
            rough_opening_windows=data.get('rough_opening_windows'),
            indicative_price_min=data.get('indicative_price_min'),
            indicative_price_max=data.get('indicative_price_max'),
            survey_required=data.get('survey_required', True),
            notes=data.get('notes'),
        )
        return jsonify(presel.to_dict()), 201
    except ValueError as exc:
        return _err(exc)
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('start_preliminary_selection error: %s', exc)
        return _err('Failed to start preliminary selection', 500)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>', methods=['PATCH'])
@login_required
def update_preselection(presel_id):
    data = request.get_json(force=True) or {}
    try:
        presel = preliminary_selection_service.update_preselection(current_user.tenant_id, presel_id, **data)
        return jsonify(presel.to_dict())
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('update_preselection error: %s', exc)
        return _err('Failed to update preliminary selection', 500)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>/shortlist', methods=['POST'])
@login_required
def shortlist_preselection(presel_id):
    try:
        presel = preliminary_selection_service.shortlist(current_user.tenant_id, presel_id)
        return jsonify(presel.to_dict())
    except LookupError as exc:
        return _err(exc, 404)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>/hold', methods=['POST'])
@login_required
def hold_preselection(presel_id):
    data = request.get_json(force=True) or {}
    try:
        presel = preliminary_selection_service.put_on_hold(current_user.tenant_id, presel_id, data.get('notes'))
        return jsonify(presel.to_dict())
    except LookupError as exc:
        return _err(exc, 404)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>/drop', methods=['POST'])
@login_required
def drop_preselection(presel_id):
    data = request.get_json(force=True) or {}
    try:
        presel = preliminary_selection_service.drop(current_user.tenant_id, presel_id, data.get('notes'))
        return jsonify(presel.to_dict())
    except LookupError as exc:
        return _err(exc, 404)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>/confirm-survey', methods=['POST'])
@login_required
def confirm_survey(presel_id):
    try:
        presel = preliminary_selection_service.confirm_survey(current_user.tenant_id, presel_id)
        return jsonify(presel.to_dict())
    except ValueError as exc:
        return _err(exc)
    except LookupError as exc:
        return _err(exc, 404)


@presel_api_bp.route('/preliminary-selections/<int:presel_id>', methods=['DELETE'])
@login_required
def delete_preselection(presel_id):
    try:
        preliminary_selection_service.delete_preselection(current_user.tenant_id, presel_id)
        return '', 204
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('delete_preselection error: %s', exc)
        return _err('Failed to delete preliminary selection', 500)
