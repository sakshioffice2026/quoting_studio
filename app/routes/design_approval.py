from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models import Project
from ..models.design_approval import DesignApprovalStatus
from ..services.domain import design_approval_service

design_approval_bp = Blueprint('design_approval', __name__)


@design_approval_bp.route('/design-approvals')
@login_required
def index():
    status = request.args.get('status') or None
    approvals = design_approval_service.list_approvals(current_user.tenant_id, status=status)
    return render_template('design_approvals.html', approvals=approvals,
                            status_filter=status, DesignApprovalStatus=DesignApprovalStatus)


@design_approval_bp.route('/design-approvals/<int:approval_id>')
@login_required
def detail(approval_id):
    approval = design_approval_service.get_approval(current_user.tenant_id, approval_id)
    if not approval:
        flash('Design approval not found.', 'error')
        return redirect(url_for('design_approval.index'))
    return render_template('design_approval_detail.html', approval=approval)


@design_approval_bp.route('/projects/<int:project_id>/design-approvals/submit', methods=['POST'])
@login_required
def submit(project_id):
    survey_id = request.form.get('survey_id', type=int)
    try:
        approval = design_approval_service.submit_for_approval(
            current_user.tenant_id, project_id, current_user.id, survey_id=survey_id
        )
        flash(f'Design submitted for approval (revision {approval.revision_number}).', 'success')
        return redirect(url_for('design_approval.detail', approval_id=approval.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('dashboard.index'))


@design_approval_bp.route('/design-approvals/<int:approval_id>/approve', methods=['POST'])
@login_required
def approve(approval_id):
    try:
        design_approval_service.approve(
            current_user.tenant_id, approval_id, current_user.id,
            customer_signoff_notes=request.form.get('customer_signoff_notes') or None,
        )
        flash('Design approved and locked.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('design_approval.detail', approval_id=approval_id))


@design_approval_bp.route('/design-approvals/<int:approval_id>/request-revision', methods=['POST'])
@login_required
def request_revision(approval_id):
    try:
        design_approval_service.request_revision(
            current_user.tenant_id, approval_id, current_user.id,
            request.form.get('reason'),
        )
        flash('Revision requested — windows unlocked for edits.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('design_approval.detail', approval_id=approval_id))
