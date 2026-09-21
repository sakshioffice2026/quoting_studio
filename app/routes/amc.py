import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models.amc import (
    AmcStatus, AmcTier, TicketStatus, ServiceType, Coverage,
)
from ..services.domain import amc_service, installation_service

amc_bp = Blueprint('amc', __name__)

_ALLOWED_CONTRACT_EXT = {'.jpg', '.jpeg', '.png', '.pdf'}


@amc_bp.app_template_global('amc_summary')
def _amc_summary(order_id):
    """Warranty / AMC / ticket summary for an order, usable in any template."""
    return amc_service.order_summary(current_user.tenant_id, order_id)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_decimal(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _save_contract(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in _ALLOWED_CONTRACT_EXT:
        raise ValueError('Signed AMC contract must be a JPG, PNG or PDF file.')
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'amc')
    os.makedirs(folder, exist_ok=True)
    name = f'{uuid.uuid4().hex}{ext}'
    file_storage.save(os.path.join(folder, name))
    return f'amc/{name}'


# ================================================================== #
#  Overview
# ================================================================== #

@amc_bp.route('/amc')
@login_required
def index():
    tenant_id = current_user.tenant_id
    status = request.args.get('status') or None
    return render_template(
        'amc.html',
        contracts=amc_service.list_contracts(tenant_id, status=status),
        status_filter=status,
        ready_orders=amc_service.orders_ready_for_warranty(tenant_id),
        warranties=amc_service.list_warranties(tenant_id),
        expiring=amc_service.expiring_contracts(tenant_id),
        AmcStatus=AmcStatus,
        AmcTier=AmcTier,
    )


# ================================================================== #
#  Warranty
# ================================================================== #

@amc_bp.route('/orders/<int:order_id>/warranty/register', methods=['POST'])
@login_required
def register_warranty(order_id):
    try:
        warranty = amc_service.register_warranty(
            tenant_id       = current_user.tenant_id,
            order_id        = order_id,
            created_by      = current_user.id,
            warranty_months = _parse_int(request.form.get('warranty_months')),
            terms           = request.form.get('terms') or None,
            start_date      = _parse_date(request.form.get('start_date')),
        )
        flash(f'Warranty {warranty.warranty_number} registered.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('amc.index'))


@amc_bp.route('/amc/warranties/<int:warranty_id>/certificate')
@login_required
def warranty_certificate(warranty_id):
    warranty = amc_service.get_warranty(current_user.tenant_id, warranty_id)
    if not warranty:
        flash('Warranty not found.', 'error')
        return redirect(url_for('amc.index'))
    return render_template('warranty_certificate.html', warranty=warranty)


# ================================================================== #
#  AMC contracts
# ================================================================== #

@amc_bp.route('/orders/<int:order_id>/amc/offer', methods=['POST'])
@login_required
def offer(order_id):
    try:
        contract = amc_service.offer_amc(
            tenant_id       = current_user.tenant_id,
            order_id        = order_id,
            created_by      = current_user.id,
            plan_tier       = request.form.get('plan_tier') or '',
            annual_fee      = _parse_decimal(request.form.get('annual_fee')),
            visits_per_year = _parse_int(request.form.get('visits_per_year')),
            notes           = request.form.get('notes') or None,
        )
        flash(f'AMC plan {contract.amc_number} offered.', 'success')
        return redirect(url_for('amc.detail', contract_id=contract.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('amc.index'))


@amc_bp.route('/amc/<int:contract_id>')
@login_required
def detail(contract_id):
    tenant_id = current_user.tenant_id
    amc_service.sweep_expired(tenant_id)
    contract = amc_service.get_contract(tenant_id, contract_id)
    if not contract:
        flash('AMC contract not found.', 'error')
        return redirect(url_for('amc.index'))
    return render_template(
        'amc_detail.html',
        contract=contract,
        tickets=[t for t in amc_service.tickets_for_order(tenant_id, contract.order_id)
                 if t.amc_contract_id == contract.id],
        final_payment_closed=amc_service.is_final_payment_closed(tenant_id, contract.order_id),
        AmcStatus=AmcStatus,
        AmcTier=AmcTier,
    )


@amc_bp.route('/amc/<int:contract_id>/activate', methods=['POST'])
@login_required
def activate(contract_id):
    try:
        contract = amc_service.activate_amc(
            tenant_id          = current_user.tenant_id,
            contract_id        = contract_id,
            signed_by          = (request.form.get('signed_by') or '').strip(),
            amc_start_date     = _parse_date(request.form.get('amc_start_date')),
            contract_file_path = _save_contract(request.files.get('contract_file')),
        )
        flash(f'AMC {contract.amc_number} is now active.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('amc.detail', contract_id=contract_id))


@amc_bp.route('/amc/<int:contract_id>/renew', methods=['POST'])
@login_required
def renew(contract_id):
    try:
        renewal = amc_service.renew_amc(
            tenant_id   = current_user.tenant_id,
            contract_id = contract_id,
            created_by  = current_user.id,
            plan_tier   = request.form.get('plan_tier') or None,
            annual_fee  = _parse_decimal(request.form.get('annual_fee')),
            notes       = request.form.get('notes') or None,
        )
        flash(f'Renewal {renewal.amc_number} offered.', 'success')
        return redirect(url_for('amc.detail', contract_id=renewal.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('amc.detail', contract_id=contract_id))


# ================================================================== #
#  Service tickets
# ================================================================== #

@amc_bp.route('/amc/tickets')
@login_required
def tickets():
    tenant_id = current_user.tenant_id
    status       = request.args.get('status') or None
    service_type = request.args.get('service_type') or None
    return render_template(
        'service_tickets.html',
        tickets=amc_service.list_tickets(tenant_id, status=status, service_type=service_type),
        warranties=amc_service.list_warranties(tenant_id),
        status_filter=status,
        type_filter=service_type,
        TicketStatus=TicketStatus,
        ServiceType=ServiceType,
    )


@amc_bp.route('/amc/orders/<int:order_id>/tickets/new')
@login_required
def ticket_new(order_id):
    tenant_id = current_user.tenant_id
    warranty = amc_service.get_warranty_for_order(tenant_id, order_id)
    if not warranty:
        flash('Register the warranty before raising a service ticket.', 'error')
        return redirect(url_for('amc.tickets'))
    return render_template(
        'service_ticket_new.html',
        order=warranty.order,
        warranty=warranty,
        openings=amc_service.installed_openings(tenant_id, order_id),
        coverage=amc_service.coverage_for(tenant_id, order_id),
        ServiceType=ServiceType,
        Coverage=Coverage,
    )


@amc_bp.route('/amc/orders/<int:order_id>/tickets/create', methods=['POST'])
@login_required
def ticket_create(order_id):
    try:
        ticket = amc_service.open_ticket(
            tenant_id       = current_user.tenant_id,
            order_id        = order_id,
            created_by      = current_user.id,
            service_type    = request.form.get('service_type') or '',
            title           = request.form.get('title') or '',
            description     = request.form.get('description') or None,
            opening_id      = _parse_int(request.form.get('opening_id')),
            reported_by     = (request.form.get('reported_by') or '').strip() or None,
            scheduled_date  = _parse_date(request.form.get('scheduled_date')),
            technician_name = (request.form.get('technician_name') or '').strip() or None,
        )
        flash(f'Ticket {ticket.ticket_number} opened ({ticket.coverage}).', 'success')
        return redirect(url_for('amc.ticket_detail', ticket_id=ticket.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('amc.ticket_new', order_id=order_id))


@amc_bp.route('/amc/tickets/<int:ticket_id>')
@login_required
def ticket_detail(ticket_id):
    ticket = amc_service.get_ticket(current_user.tenant_id, ticket_id)
    if not ticket:
        flash('Service ticket not found.', 'error')
        return redirect(url_for('amc.tickets'))
    return render_template(
        'service_ticket_detail.html',
        ticket=ticket,
        TicketStatus=TicketStatus,
    )


@amc_bp.route('/amc/tickets/<int:ticket_id>/schedule', methods=['POST'])
@login_required
def ticket_schedule(ticket_id):
    try:
        ticket = amc_service.schedule_ticket(
            tenant_id       = current_user.tenant_id,
            ticket_id       = ticket_id,
            scheduled_date  = _parse_date(request.form.get('scheduled_date')),
            technician_name = (request.form.get('technician_name') or '').strip() or None,
        )
        flash(f'Ticket {ticket.ticket_number} scheduled.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('amc.ticket_detail', ticket_id=ticket_id))


@amc_bp.route('/amc/tickets/<int:ticket_id>/start', methods=['POST'])
@login_required
def ticket_start(ticket_id):
    try:
        ticket = amc_service.start_ticket(
            tenant_id       = current_user.tenant_id,
            ticket_id       = ticket_id,
            technician_name = (request.form.get('technician_name') or '').strip() or None,
        )
        flash(f'Ticket {ticket.ticket_number} started.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('amc.ticket_detail', ticket_id=ticket_id))


@amc_bp.route('/amc/tickets/<int:ticket_id>/resolve', methods=['POST'])
@login_required
def ticket_resolve(ticket_id):
    try:
        ticket = amc_service.resolve_ticket(
            tenant_id        = current_user.tenant_id,
            ticket_id        = ticket_id,
            resolution_notes = request.form.get('resolution_notes') or '',
            resolved_by      = (request.form.get('resolved_by') or '').strip(),
        )
        flash(f'Ticket {ticket.ticket_number} resolved.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('amc.ticket_detail', ticket_id=ticket_id))
