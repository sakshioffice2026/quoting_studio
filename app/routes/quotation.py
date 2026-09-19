from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models import Project
from ..models.quotation import QuotationStatus
from ..services.domain import quotation_service

quotation_bp = Blueprint('quotation', __name__)


# ------------------------------------------------------------------ #
#  GET /quotations  — list all quotations for tenant
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations')
@login_required
def index():
    status = request.args.get('status') or None
    quotation_service.expire_overdue(current_user.tenant_id)
    quotations = quotation_service.list_quotations(current_user.tenant_id, status=status)
    return render_template(
        'quotations.html',
        quotations=quotations,
        status_filter=status,
        QuotationStatus=QuotationStatus,
    )


# ------------------------------------------------------------------ #
#  GET /quotations/<id>  — detail view
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>')
@login_required
def detail(quotation_id):
    q = quotation_service.get_quotation(current_user.tenant_id, quotation_id)
    if not q:
        flash('Quotation not found.', 'error')
        return redirect(url_for('quotation.index'))
    if q.is_expired and q.status == QuotationStatus.SENT:
        quotation_service.expire_overdue(current_user.tenant_id)
        q = quotation_service.get_quotation(current_user.tenant_id, quotation_id)
    return render_template(
        'quotation_detail.html',
        quotation=q,
        QuotationStatus=QuotationStatus,
    )


# ------------------------------------------------------------------ #
#  POST /projects/<id>/quotations/generate
# ------------------------------------------------------------------ #
@quotation_bp.route('/projects/<int:project_id>/quotations/generate', methods=['POST'])
@login_required
def generate(project_id):
    discount_pct           = request.form.get('discount_pct',           type=float, default=0.0)
    validity_days          = request.form.get('validity_days',           type=int,   default=30)
    payment_terms_template = request.form.get('payment_terms_template') or None
    try:
        q = quotation_service.create_quotation(
            tenant_id              = current_user.tenant_id,
            project_id             = project_id,
            prepared_by            = current_user.id,
            discount_pct           = discount_pct,
            validity_days          = validity_days,
            payment_terms_template = payment_terms_template,
        )
        if q.status == QuotationStatus.PENDING_DISCOUNT_APPROVAL:
            flash(
                f'Quotation {q.quotation_number} created — '
                f'discount >{int(discount_pct)}% requires manager approval before sending.',
                'warning',
            )
        else:
            flash(f'Quotation {q.quotation_number} (v{q.quotation_version}) created.', 'success')
        return redirect(url_for('quotation.detail', quotation_id=q.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/approve-discount
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>/approve-discount', methods=['POST'])
@login_required
def approve_discount(quotation_id):
    try:
        q = quotation_service.approve_discount(
            current_user.tenant_id, quotation_id, current_user.id
        )
        flash(f'Discount approved — {q.quotation_number} is now ready to send.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation.detail', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/send
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>/send', methods=['POST'])
@login_required
def send_to_customer(quotation_id):
    try:
        q = quotation_service.send_to_customer(
            current_user.tenant_id, quotation_id, current_user.id
        )
        flash(
            f'Quotation {q.quotation_number} sent to customer — '
            f'valid until {q.validity_date.strftime("%Y-%m-%d") if q.validity_date else "N/A"}.',
            'success',
        )
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation.detail', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/negotiation
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>/negotiation', methods=['POST'])
@login_required
def mark_negotiation(quotation_id):
    notes = request.form.get('notes') or None
    try:
        quotation_service.mark_negotiation(current_user.tenant_id, quotation_id, notes=notes)
        flash('Quotation moved to negotiation.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation.detail', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/accept
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>/accept', methods=['POST'])
@login_required
def accept(quotation_id):
    accepted_by_name  = request.form.get('accepted_by_name', '').strip()
    acceptance_method = request.form.get('acceptance_method', 'email')
    if not accepted_by_name:
        flash('Customer name is required to accept a quotation.', 'error')
        return redirect(url_for('quotation.detail', quotation_id=quotation_id))
    try:
        q = quotation_service.accept_quotation(
            tenant_id         = current_user.tenant_id,
            quotation_id      = quotation_id,
            accepted_by_name  = accepted_by_name,
            acceptance_method = acceptance_method,
        )
        flash(f'Quotation {q.quotation_number} accepted — proceed to Order Acceptance.', 'success')
        return redirect(url_for('quotation.detail', quotation_id=quotation_id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('quotation.detail', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/lost
# ------------------------------------------------------------------ #
@quotation_bp.route('/quotations/<int:quotation_id>/lost', methods=['POST'])
@login_required
def mark_lost(quotation_id):
    lost_reason = request.form.get('lost_reason', '').strip()
    if not lost_reason:
        flash('A lost reason is required.', 'error')
        return redirect(url_for('quotation.detail', quotation_id=quotation_id))
    try:
        q = quotation_service.mark_lost(
            current_user.tenant_id, quotation_id, lost_reason
        )
        flash(f'Quotation {q.quotation_number} marked as lost.', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation.detail', quotation_id=quotation_id))
