from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from ..models.payment import PaymentStatus, PaymentStage, ReleaseMode
from ..models.order_unit_release import UnitReleaseStatus
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
    release_progress = {}
    for p in payments:
        if p.payment_stage == PaymentStage.ADVANCE and p.is_unit_wise:
            rows = payment_service.list_unit_releases(current_user.tenant_id, p.id)
            release_progress[p.id] = {
                'released': sum(1 for r in rows if r.is_released),
                'total':    len(rows),
            }
    return render_template(
        'payments.html',
        payments=payments,
        status_filter=status,
        PaymentStatus=PaymentStatus,
        ReleaseMode=ReleaseMode,
        release_progress=release_progress,
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
    receipts      = payment_service.list_receipts(current_user.tenant_id, p.id)
    unit_releases = (payment_service.list_unit_releases(current_user.tenant_id, p.id)
                     if p.is_unit_wise else [])
    return render_template(
        'payment_detail.html',
        payment=p,
        receipts=receipts,
        unit_releases=unit_releases,
        PaymentStatus=PaymentStatus,
        PaymentStage=PaymentStage,
        ReleaseMode=ReleaseMode,
        UnitReleaseStatus=UnitReleaseStatus,
    )


# ------------------------------------------------------------------ #
#  POST /orders/<id>/payments/raise
# ------------------------------------------------------------------ #
@payment_bp.route('/orders/<int:order_id>/payments/raise', methods=['POST'])
@login_required
def raise_invoice(order_id):
    payment_stage  = request.form.get('payment_stage', PaymentStage.ADVANCE)
    invoice_amount = request.form.get('invoice_amount', type=float, default=0.0)
    release_mode   = request.form.get('release_mode', ReleaseMode.WHOLE_ORDER)
    advance_pct    = request.form.get('advance_pct', type=float, default=50.0)
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
            release_mode   = release_mode,
            advance_pct    = advance_pct,
        )
        flash(f'Invoice {p.payment_number} raised for {p.stage_label}.', 'success')
        return redirect(url_for('payment.detail', payment_id=p.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  POST /orders/<id>/payments/auto-invoice  — next stage(s), auto-calculated
# ------------------------------------------------------------------ #
@payment_bp.route('/orders/<int:order_id>/payments/auto-invoice', methods=['POST'])
@login_required
def auto_invoice(order_id):
    due_date = request.form.get('due_date') or None
    if due_date:
        due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
    try:
        raised = payment_service.auto_invoice_stages(
            current_user.tenant_id, order_id, raised_by=current_user.id,
            due_date=due_date, force_next=True)
        if raised:
            flash('Invoice raised: ' + ', '.join(
                f'{p.payment_number} ({p.stage_label})' for p in raised), 'success')
        else:
            flash('All payment milestones are already invoiced.', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  GET /orders/<id>/units/balances  — live per-unit dues and lock state
# ------------------------------------------------------------------ #
@payment_bp.route('/orders/<int:order_id>/units/balances')
@login_required
def unit_balances(order_id):
    tid = current_user.tenant_id
    return jsonify(
        summary=payment_service.order_payment_summary(tid, order_id),
        units=payment_service.unit_balances(tid, order_id),
    )


# ------------------------------------------------------------------ #
#  POST /payments/<id>/policy  — release mode + advance %
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/policy', methods=['POST'])
@login_required
def update_policy(payment_id):
    release_mode = request.form.get('release_mode', ReleaseMode.WHOLE_ORDER)
    advance_pct  = request.form.get('advance_pct') or None
    try:
        p = payment_service.update_release_policy(
            current_user.tenant_id, payment_id, release_mode, advance_pct)
        flash(f'Release policy updated: {p.release_mode_label}, {p.advance_pct}% advance.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/priority  — reorder units for unit-wise release
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/priority', methods=['POST'])
@login_required
def reorder_units(payment_id):
    raw = request.form.get('order', '')
    try:
        ids = [int(x) for x in raw.split(',') if x.strip()]
    except ValueError:
        flash('Invalid priority order.', 'error')
        return redirect(url_for('payment.detail', payment_id=payment_id))
    try:
        payment_service.reorder_units(current_user.tenant_id, payment_id, ids)
        flash('Unit priority updated.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('payment.detail', payment_id=payment_id))


# ------------------------------------------------------------------ #
#  POST /payments/<id>/receipt
# ------------------------------------------------------------------ #
@payment_bp.route('/payments/<int:payment_id>/receipt', methods=['POST'])
@login_required
def record_receipt(payment_id):
    amount_received = request.form.get('amount_received', type=float, default=0.0)
    payment_mode    = request.form.get('payment_mode', '').strip()
    transaction_ref = request.form.get('transaction_ref') or None
    notes           = request.form.get('notes') or None
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
            recorded_by     = current_user.id,
            notes           = notes,
        )
        if p.is_unit_wise and p.payment_stage == PaymentStage.ADVANCE:
            rows = payment_service.list_unit_releases(current_user.tenant_id, p.id)
            done = sum(1 for r in rows if r.is_released)
            flash(f'Receipt recorded. {done} of {len(rows)} units released to manufacturing.',
                  'success' if done else 'warning')
        elif p.status == PaymentStatus.RECEIVED and p.payment_stage == PaymentStage.ADVANCE:
            from ..services.domain import manufacturing_service
            jobs = manufacturing_service.list_for_order(current_user.tenant_id, p.order_id)
            if jobs:
                flash(f'Advance {p.payment_number} received. Quotation locked and '
                      f'{len(jobs)} manufacturing job(s) queued: Cutting → Machining → '
                      f'Assembly → Glazing → Quality Check.', 'success')
            else:
                flash(f'Advance {p.payment_number} received, but no manufacturing jobs '
                      f'could be queued. Check the order has openings.', 'warning')
        elif p.status == PaymentStatus.RECEIVED:
            flash(f'Payment {p.payment_number} fully received.', 'success')
        else:
            flash(f'Partial payment recorded for {p.payment_number}. Balance: {p.balance}', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    except Exception as exc:
        flash(f'Could not record receipt: {exc}', 'error')
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
