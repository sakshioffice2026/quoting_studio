import os
import uuid
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models.delivery import DeliveryStatus
from ..services.domain import delivery_service

delivery_bp = Blueprint('delivery', __name__)

_ALLOWED_POD_EXT = {'.jpg', '.jpeg', '.png', '.pdf'}


@delivery_bp.app_template_global('opening_progress')
def _opening_progress(order_id):
    """Per-opening manufacturing/delivery progress for use in any template."""
    return delivery_service.opening_progress(current_user.tenant_id, order_id)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _save_pod(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in _ALLOWED_POD_EXT:
        raise ValueError('Proof of delivery must be a JPG, PNG or PDF file.')
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pod')
    os.makedirs(folder, exist_ok=True)
    name = f'{uuid.uuid4().hex}{ext}'
    file_storage.save(os.path.join(folder, name))
    return f'pod/{name}'


# ------------------------------------------------------------------ #
#  GET /deliveries
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries')
@login_required
def index():
    status = request.args.get('status') or None
    deliveries = delivery_service.list_deliveries(current_user.tenant_id, status=status)
    return render_template(
        'deliveries.html',
        deliveries=deliveries,
        status_filter=status,
        DeliveryStatus=DeliveryStatus,
    )


# ------------------------------------------------------------------ #
#  GET /deliveries/<id>
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>')
@login_required
def detail(delivery_id):
    delivery = delivery_service.get_delivery(current_user.tenant_id, delivery_id)
    if not delivery:
        flash('Delivery not found.', 'error')
        return redirect(url_for('delivery.index'))
    return render_template(
        'delivery_detail.html',
        delivery=delivery,
        DeliveryStatus=DeliveryStatus,
    )


# ------------------------------------------------------------------ #
#  GET /deliveries/<id>/challan  — printable challan / packing list
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>/challan')
@login_required
def challan(delivery_id):
    delivery = delivery_service.get_delivery(current_user.tenant_id, delivery_id)
    if not delivery:
        flash('Delivery not found.', 'error')
        return redirect(url_for('delivery.index'))
    return render_template('delivery_challan.html', delivery=delivery)


# ------------------------------------------------------------------ #
#  POST /orders/<id>/deliveries/create   (pack)
# ------------------------------------------------------------------ #
@delivery_bp.route('/orders/<int:order_id>/deliveries/create', methods=['POST'])
@login_required
def create(order_id):
    opening_ids = [int(x) for x in request.form.getlist('opening_ids') if x.isdigit()]
    labels = {}
    for oid in opening_ids:
        label = request.form.get(f'package_label_{oid}')
        if label:
            labels[oid] = label.strip()
    try:
        delivery = delivery_service.create_delivery(
            tenant_id               = current_user.tenant_id,
            order_id                = order_id,
            created_by              = current_user.id,
            opening_ids             = opening_ids or None,
            delivery_address        = request.form.get('delivery_address') or None,
            site_contact_name       = request.form.get('site_contact_name') or None,
            site_contact_phone      = request.form.get('site_contact_phone') or None,
            scheduled_dispatch_date = _parse_date(request.form.get('scheduled_dispatch_date')),
            package_labels          = labels or None,
        )
        flash(f'Delivery {delivery.delivery_number} packed.', 'success')
        return redirect(url_for('delivery.detail', delivery_id=delivery.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  POST /deliveries/<id>/dispatch
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>/dispatch', methods=['POST'])
@login_required
def dispatch(delivery_id):
    try:
        delivery = delivery_service.dispatch_delivery(
            tenant_id        = current_user.tenant_id,
            delivery_id      = delivery_id,
            vehicle_ref      = (request.form.get('vehicle_ref') or '').strip(),
            transporter_name = request.form.get('transporter_name') or None,
            driver_name      = request.form.get('driver_name') or None,
            driver_phone     = request.form.get('driver_phone') or None,
            assigned_to      = current_user.id,
        )
        flash(f'Delivery {delivery.delivery_number} dispatched.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('delivery.detail', delivery_id=delivery_id))


# ------------------------------------------------------------------ #
#  POST /deliveries/<id>/confirm
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>/confirm', methods=['POST'])
@login_required
def confirm(delivery_id):
    delivery = delivery_service.get_delivery(current_user.tenant_id, delivery_id)
    if not delivery:
        flash('Delivery not found.', 'error')
        return redirect(url_for('delivery.index'))

    item_issues = []
    for item in delivery.items:
        damaged = request.form.get(f'damaged_{item.opening_id}') == 'on'
        short   = request.form.get(f'short_{item.opening_id}') == 'on'
        notes   = request.form.get(f'issue_notes_{item.opening_id}') or None
        if damaged or short:
            item_issues.append({
                'opening_id':  item.opening_id,
                'is_damaged':  damaged,
                'is_short':    short,
                'issue_notes': notes,
            })

    try:
        pod_path = _save_pod(request.files.get('pod_file'))
        delivery = delivery_service.confirm_delivery(
            tenant_id             = current_user.tenant_id,
            delivery_id           = delivery_id,
            received_by           = (request.form.get('received_by') or '').strip(),
            item_issues           = item_issues,
            damage_shortage_notes = request.form.get('damage_shortage_notes') or None,
            pod_file_path         = pod_path,
        )
        if delivery.status == DeliveryStatus.DELIVERED_WITH_ISSUES:
            flash(f'Delivery {delivery.delivery_number} received with issues.', 'warning')
        else:
            flash(f'Delivery {delivery.delivery_number} received.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('delivery.detail', delivery_id=delivery_id))


# ------------------------------------------------------------------ #
#  POST /deliveries/<id>/items/<item_id>/resolve
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>/items/<int:item_id>/resolve', methods=['POST'])
@login_required
def resolve_item(delivery_id, item_id):
    try:
        delivery_service.resolve_item_issue(
            current_user.tenant_id, delivery_id, item_id,
            resolution_notes=request.form.get('resolution_notes') or None,
        )
        flash('Issue marked as resolved.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('delivery.detail', delivery_id=delivery_id))


# ------------------------------------------------------------------ #
#  POST /deliveries/<id>/resolve-all
# ------------------------------------------------------------------ #
@delivery_bp.route('/deliveries/<int:delivery_id>/resolve-all', methods=['POST'])
@login_required
def resolve_all(delivery_id):
    try:
        delivery = delivery_service.resolve_all_issues(
            current_user.tenant_id, delivery_id,
            resolution_notes=request.form.get('resolution_notes') or None,
        )
        flash(f'All issues resolved; delivery {delivery.delivery_number} marked delivered.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('delivery.detail', delivery_id=delivery_id))
