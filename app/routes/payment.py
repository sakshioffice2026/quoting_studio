from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models.payment import PaymentStatus, PaymentStage
from ..services.domain import payment_service

payment_bp = Blueprint('payment', __name__)


# ------------------------------------------------------------------ #
#  GET /payments  — list all payments for tenant
# ------------------------------------------------------------------ #
@payment_bp.route('/payments')
@login_required
def index():
    status = request.args.get('status') or None
    payment_service.mark_overdue(current_user.tenant_id)
    payments = payment_service.list_payments(current_user.tenant_id, status=status)
    return render_template(
        'payments.html',
        payments=payments,
        status_filter=status,
        PaymentStatus=PaymentStatus,
    )


# ------------------------------------------------------------------ #
#  GET /payments/<id>  — detail view
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>')
@login_required
def detail(payment_id):
    p = payment_service.get_payment(current_user.tenant_id, payment_id)
    if not p:
        flash('Payment not found.', 'error')
        return redirect(url_for('payment.index'))
    return render_template(
        'payment_detail.html',
        payment=p,
        PaymentStatus=PaymentStatus,
    )


# ------------------------------------------------------------------ #
#  POST /orders/<id>/payments/raise
# ------------------------------------------------------------------ #
@payment_bp.route('/orders/<int:order_id>/payments/raise', methods=['POST'])
@login_required
def raise_invoice(order_id):
    payment_stage  = request.form.get('payment_stage', PaymentStage.ADVANCE)
    invoice_amount = request.form.get('invoice_amount', type=float, default=0.0)
    due_date       = request.form.get('due_date') or None
    if due_date:
        due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
    try:
        p = payment_service.raise_invoice(
            tenant_id      = current_user.tenant_id,
            order_id       = order_id,
            raised_by      = current_user.id,
            payment_stage  = payment_stage,
            invoice_amount = invoice_amount,
            due_date       = due_date,
        )
        flash(f'Invoice {p.payment_number} raised for {p.stage_label}.', 'success')
        return redirect(url_for('payment.detail', payment_id=p.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/receipt
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/receipt', methods=['POST'])
@login_required
def record_receipt(payment_id):
    amount_received = request.form.get('amount_received', type=float, default=0.0)
    payment_mode    = request.form.get('payment_mode', '').strip()
    transaction_ref = request.form.get('transaction_ref') or None
    if not payment_mode:
        flash('Payment mode is required.', 'error')
        return redirect(url_for('payment.detail', payment_id=payment_id))
    try:
        p = payment_service.record_receipt(
            tenant_id       = current_user.tenant_id,
            payment_id      = payment_id,
            amount_received = amount_received,
            payment_mode    = payment_mode,
            transaction_ref = transaction_ref,
        )
        if p.status == PaymentStatus.RECEIVED:
            flash(f'Payment {p.payment_number} fully received.', 'success')
        else:
            flash(f'Partial payment recorded for {p.payment_number}. Balance: {p.balance}', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/hold
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/hold', methods=['POST'])
@login_required
def apply_hold(payment_id):
    hold_reason = request.form.get('hold_reason', '').strip()
    if not hold_reason:
        flash('A hold reason is required.', 'error')
        return redirect(url_for('payment.detail', payment_id=payment_id))
    try:
        p = payment_service.apply_hold(current_user.tenant_id, payment_id, hold_reason)
        flash(f'Hold applied on {p.payment_number}.', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/release-hold
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/release-hold', methods=['POST'])
@login_required
def release_hold(payment_id):
    try:
        p = payment_service.release_hold(current_user.tenant_id, payment_id)
        flash(f'Hold released on {p.payment_number}.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/close
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/close', methods=['POST'])
@login_required
def close(payment_id):
    try:
        p = payment_service.close_payment(current_user.tenant_id, payment_id)
        flash(f'Payment {p.payment_number} closed.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))
