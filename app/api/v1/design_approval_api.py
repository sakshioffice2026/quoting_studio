from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ...services.domain import design_approval_service

design_approval_api_bp = Blueprint('design_approval_api', __name__)


def _err(exc, code=400):
    return jsonify({'error': str(exc)}), code


@design_approval_api_bp.route('/projects/<int:project_id>/design-approvals', methods=['GET'])
@login_required
def list_for_project(project_id):
    approvals = design_approval_service.list_for_project(current_user.tenant_id, project_id)
    return jsonify([a.to_dict() for a in approvals])


@design_approval_api_bp.route('/projects/<int:project_id>/design-approvals/latest', methods=['GET'])
@login_required
def latest_for_project(project_id):
    approval = design_approval_service.get_latest_for_project(current_user.tenant_id, project_id)
    if not approval:
        return jsonify(None)
    return jsonify(approval.to_dict())


@design_approval_api_bp.route('/design-approvals', methods=['GET'])
@login_required
def list_all():
    status = request.args.get('status') or None
    approvals = design_approval_service.list_approvals(current_user.tenant_id, status=status)
    return jsonify([a.to_dict() for a in approvals])


@design_approval_api_bp.route('/design-approvals/<int:approval_id>', methods=['GET'])
@login_required
def get_approval(approval_id):
    approval = design_approval_service.get_approval(current_user.tenant_id, approval_id)
    if not approval:
        return jsonify({'error': 'Design approval not found'}), 404
    return jsonify(approval.to_dict())


@design_approval_api_bp.route('/projects/<int:project_id>/design-approvals/submit', methods=['POST'])
@login_required
def submit(project_id):
    data = request.get_json(force=True) or {}
    try:
        approval = design_approval_service.submit_for_approval(
            tenant_id=current_user.tenant_id,
            project_id=project_id,
            submitted_by=current_user.id,
            survey_id=data.get('survey_id'),
        )
        return jsonify(approval.to_dict()), 201
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)
    except Exception as exc:
        current_app.logger.exception('design approval submit error: %s', exc)
        return _err('Failed to submit design for approval', 500)


@design_approval_api_bp.route('/design-approvals/<int:approval_id>/approve', methods=['POST'])
@login_required
def approve(approval_id):
    data = request.get_json(force=True) or {}
    try:
        approval = design_approval_service.approve(
            current_user.tenant_id, approval_id, current_user.id,
            customer_signoff_notes=data.get('customer_signoff_notes'),
        )
        return jsonify(approval.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@design_approval_api_bp.route('/design-approvals/<int:approval_id>/request-revision', methods=['POST'])
@login_required
def request_revision(approval_id):
    data = request.get_json(force=True) or {}
    try:
        approval = design_approval_service.request_revision(
            current_user.tenant_id, approval_id, current_user.id, data.get('reason')
        )
        return jsonify(approval.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@design_approval_api_bp.route('/design-approvals/<int:approval_id>/send', methods=['POST'])
@login_required
def send_to_customer(approval_id):
    """DESIGN-SUBMITTED → APPROVAL-SENT. Optionally pass sla_days to override the default."""
    data = request.get_json(force=True) or {}
    try:
        approval = design_approval_service.send_to_customer(
            current_user.tenant_id, approval_id, current_user.id,
            sla_days=data.get('sla_days'),
        )
        return jsonify(approval.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@design_approval_api_bp.route('/design-approvals/<int:approval_id>/resend', methods=['POST'])
@login_required
def resend_to_customer(approval_id):
    """APPROVAL-EXPIRED → APPROVAL-SENT (restart SLA clock)."""
    data = request.get_json(force=True) or {}
    try:
        approval = design_approval_service.resend_to_customer(
            current_user.tenant_id, approval_id, current_user.id,
            sla_days=data.get('sla_days'),
        )
        return jsonify(approval.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@design_approval_api_bp.route('/design-approvals/<int:approval_id>/expire', methods=['POST'])
@login_required
def expire(approval_id):
    """Manually mark an APPROVAL-SENT record as APPROVAL-EXPIRED."""
    try:
        approval = design_approval_service.expire_approval(current_user.tenant_id, approval_id)
        return jsonify(approval.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@design_approval_api_bp.route('/design-approvals/expire-overdue', methods=['POST'])
@login_required
def expire_overdue():
    """Batch: flip all APPROVAL-SENT records past their SLA deadline to APPROVAL-EXPIRED.
    Intended for a cron/scheduler to call — scoped to current tenant.
    """
    count = design_approval_service.expire_overdue(current_user.tenant_id)
    return jsonify({'expired_count': count})
