from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models.order import Order, OrderStatus
from ..models.payment import PaymentStatus, PaymentStage
from ..models.manufacturing_job import JobStatus
from ..models.delivery import DeliveryStatus
from ..models.installation import InstallationStatus
from ..models.amc import AmcStatus, AmcTier, WarrantyStatus
from ..services.domain import order_service

order_bp = Blueprint('order', __name__)


# ------------------------------------------------------------------ #
#  GET /orders  — list all orders for tenant
# ------------------------------------------------------------------ #
@order_bp.route('/orders')
@login_required
def index():
    status = request.args.get('status') or None
    orders = order_service.list_orders(current_user.tenant_id, status=status)
    return render_template(
        'orders.html',
        orders=orders,
        status_filter=status,
        OrderStatus=OrderStatus,
    )


# ------------------------------------------------------------------ #
#  GET /orders/<id>  — detail view
# ------------------------------------------------------------------ #
@order_bp.route('/orders/<int:order_id>')
@login_required
def detail(order_id):
    o = order_service.get_order(current_user.tenant_id, order_id)
    if not o:
        flash('Order not found.', 'error')
        return redirect(url_for('order.index'))
    return render_template(
        'order_detail.html',
        order=o,
        OrderStatus=OrderStatus,
        PaymentStatus=PaymentStatus,
        PaymentStage=PaymentStage,
        JobStatus=JobStatus,
        DeliveryStatus=DeliveryStatus,
        InstallationStatus=InstallationStatus,
        AmcStatus=AmcStatus,
        AmcTier=AmcTier,
        WarrantyStatus=WarrantyStatus,
    )


# ------------------------------------------------------------------ #
#  POST /quotations/<id>/orders/create
# ------------------------------------------------------------------ #
@order_bp.route('/quotations/<int:quotation_id>/orders/create', methods=['POST'])
@login_required
def create(quotation_id):
    contract_ref = request.form.get('contract_ref') or None
    promised_delivery_date = request.form.get('promised_delivery_date') or None
    if promised_delivery_date:
        from datetime import datetime
        promised_delivery_date = datetime.strptime(promised_delivery_date, '%Y-%m-%d').date()
    try:
        o = order_service.create_order(
            tenant_id              = current_user.tenant_id,
            quotation_id           = quotation_id,
            created_by             = current_user.id,
            contract_ref           = contract_ref,
            promised_delivery_date = promised_delivery_date,
        )
        flash(f'Order {o.order_number} created — awaiting customer signature.', 'success')
        return redirect(url_for('order.detail', order_id=o.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('quotation.detail', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /orders/<id>/confirm
# ------------------------------------------------------------------ #
@order_bp.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm(order_id):
    order = Order.query.filter_by(id=order_id, tenant_id=current_user.tenant_id).first()
    if order is not None and order.project is not None:
        order_confirmed_by_name = order.project.customer_name
    else:
        order_confirmed_by_name = request.form.get('order_confirmed_by_name', '').strip()
    confirmation_method      = request.form.get('confirmation_method', 'email')
    assigned_project_manager = request.form.get('assigned_project_manager', type=int)
    if not order_confirmed_by_name:
        flash('Customer name is missing on this project.', 'error')
        return redirect(url_for('order.detail', order_id=order_id))
    try:
        o = order_service.confirm_order(
            tenant_id                = current_user.tenant_id,
            order_id                 = order_id,
            order_confirmed_by_name  = order_confirmed_by_name,
            confirmation_method      = confirmation_method,
            assigned_project_manager = assigned_project_manager,
        )
        flash(f'Order {o.order_number} confirmed — proceed to Advance Payment.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  POST /orders/<id>/cancel
# ------------------------------------------------------------------ #
@order_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel(order_id):
    cancelled_reason = request.form.get('cancelled_reason', '').strip()
    if not cancelled_reason:
        flash('A cancellation reason is required.', 'error')
        return redirect(url_for('order.detail', order_id=order_id))
    try:
        o = order_service.cancel_order(
            current_user.tenant_id, order_id, cancelled_reason
        )
        flash(f'Order {o.order_number} cancelled.', 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('order.detail', order_id=order_id))
