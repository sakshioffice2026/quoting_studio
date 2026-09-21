"""
Timeline (/leads/<id>/flow) data for Sections 7–13, built from live project data.

build_downstream(tenant_id, project_id) returns a dict keyed by stage key:
    quotation, order, advance_payment, payment_journey,
    manufacturing, delivery, installation

Each value: {'status_label', 'url', 'date_label', 'date', 'tip': [(label, value), ...]}
Stages with no data yet are omitted (they stay "Not started" on the timeline).
"""
from flask import current_app, url_for
from sqlalchemy import desc

from ...models.quotation import Quotation, QuotationStatus
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStage, PaymentStatus
from ...models.manufacturing_job import ManufacturingJob, JobStatus
from ...models.delivery import Delivery, DeliveryStatus


# ------------------------------------------------------------------ #
#  Formatting helpers
# ------------------------------------------------------------------ #

def _d(value):
    return value.strftime('%d %b %Y') if value else None


def _dt(value):
    return value.strftime('%d %b %Y, %H:%M') if value else None


def _money(value):
    if value is None:
        return None
    try:
        return '{:,.2f}'.format(float(value))
    except (TypeError, ValueError):
        return None


def _status(code, labels):
    return '%s (%s)' % (labels.get(code, code), code)


def _s(value):
    return None if value is None else str(value)


# ------------------------------------------------------------------ #
#  Section 7 — Quotation
# ------------------------------------------------------------------ #

def _quotation(tenant_id, project_id):
    quotes = (Quotation.query
              .filter_by(tenant_id=tenant_id, project_id=project_id)
              .order_by(desc(Quotation.created_at))
              .all())
    if not quotes:
        return None

    q = next((x for x in quotes if x.status == QuotationStatus.ACCEPTED), quotes[0])

    if q.accepted_at:
        date_label, date_value = 'Accepted', q.accepted_at
    elif q.sent_at:
        date_label, date_value = 'Sent', q.sent_at
    else:
        date_label, date_value = 'Created', q.created_at

    return {
        'status_label': q.status,
        'url':          url_for('quotation.detail', quotation_id=q.id),
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(q.status, QuotationStatus.LABELS)),
            ('Quotation', '%s (v%s)' % (q.quotation_number, q.quotation_version)),
            ('Quotations on project', str(len(quotes))),
            ('Grand total', _money(q.grand_total)),
            ('Discount', '%s%%' % q.discount_pct if q.discount_pct else None),
            ('Valid until', _d(q.validity_date)),
            ('Sent', _dt(q.sent_at)),
            ('Accepted', _dt(q.accepted_at)),
            ('Accepted by', q.accepted_by_name),
            ('Lost reason', q.lost_reason),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 8 — Order
# ------------------------------------------------------------------ #

def _order(orders):
    if not orders:
        return None

    active = [o for o in orders if o.status != OrderStatus.CANCELLED]
    o = active[-1] if active else orders[-1]

    if o.order_confirmed_at:
        date_label, date_value = 'Confirmed', o.order_confirmed_at
    else:
        date_label, date_value = 'Created', o.created_at

    return {
        'status_label': o.status,
        'url':          url_for('order.detail', order_id=o.id),
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(o.status, OrderStatus.LABELS)),
            ('Order', o.order_number),
            ('Contract ref', o.contract_ref),
            ('Order value', _money(o.total_amount)),
            ('Confirmed', _dt(o.order_confirmed_at)),
            ('Confirmed by', o.order_confirmed_by_name),
            ('Promised delivery', _d(o.promised_delivery_date)),
            ('Cancelled reason', o.cancelled_reason),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 9 — Advance Payment
# ------------------------------------------------------------------ #

def _advance_payment(tenant_id, order_ids):
    if not order_ids:
        return None
    payments = (Payment.query
                .filter(Payment.tenant_id == tenant_id,
                        Payment.order_id.in_(order_ids),
                        Payment.payment_stage == PaymentStage.ADVANCE)
                .order_by(Payment.created_at)
                .all())
    if not payments:
        return None

    p = payments[-1]
    if p.received_at:
        date_label, date_value = 'Received', p.received_at
    else:
        date_label, date_value = 'Invoiced', p.created_at

    return {
        'status_label': p.status,
        'url':          url_for('payment.detail', payment_id=p.id),
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(p.status, PaymentStatus.LABELS)),
            ('Payment', p.payment_number),
            ('Invoice amount', _money(p.invoice_amount)),
            ('Received', _money(p.amount_received)),
            ('Balance', _money(p.balance)),
            ('Due date', _d(p.due_date)),
            ('Received on', _dt(p.received_at)),
            ('Payment mode', p.payment_mode),
            ('Hold reason', p.hold_reason if p.hold_flag else None),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 10 — Payment Journey
# ------------------------------------------------------------------ #

def _payment_journey(tenant_id, order_ids):
    if not order_ids:
        return None
    payments = (Payment.query
                .filter(Payment.tenant_id == tenant_id,
                        Payment.order_id.in_(order_ids))
                .order_by(Payment.created_at)
                .all())
    if not payments:
        return None

    settled_states = (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)
    statuses = [p.status for p in payments]

    if all(s == PaymentStatus.CLOSED for s in statuses):
        status = PaymentStatus.CLOSED
    elif any(s == PaymentStatus.HOLD_APPLIED or p.hold_flag for s, p in zip(statuses, payments)):
        status = PaymentStatus.HOLD_APPLIED
    elif any(p.is_overdue or p.status == PaymentStatus.OVERDUE for p in payments):
        status = PaymentStatus.OVERDUE
    elif all(s in settled_states for s in statuses):
        status = PaymentStatus.RECEIVED
    elif any(s in settled_states or s == PaymentStatus.PARTIAL for s in statuses):
        status = PaymentStatus.PARTIAL
    else:
        status = PaymentStatus.INVOICED

    total_inv = sum(float(p.invoice_amount or 0) for p in payments)
    total_rec = sum(float(p.amount_received or 0) for p in payments)
    settled   = sum(1 for p in payments if p.status in settled_states)
    due_dates = [p.due_date for p in payments if p.status not in settled_states and p.due_date]

    return {
        'status_label': status,
        'url':          url_for('payment.index'),
        'date_label':   'First invoice',
        'date':         _d(payments[0].created_at),
        'tip': [
            ('Current status', _status(status, PaymentStatus.LABELS)),
            ('Milestones invoiced', str(len(payments))),
            ('Milestones settled', '%s of %s' % (settled, len(payments))),
            ('Total invoiced', _money(total_inv)),
            ('Total received', _money(total_rec)),
            ('Outstanding', _money(total_inv - total_rec)),
            ('Next due', _d(min(due_dates)) if due_dates else None),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 11 — Manufacturing
# ------------------------------------------------------------------ #

def _manufacturing(tenant_id, order_ids):
    if not order_ids:
        return None
    jobs = (ManufacturingJob.query
            .filter(ManufacturingJob.tenant_id == tenant_id,
                    ManufacturingJob.order_id.in_(order_ids))
            .order_by(ManufacturingJob.created_at)
            .all())
    if not jobs:
        return None

    completed   = [j for j in jobs if j.status == JobStatus.COMPLETED]
    in_progress = [j for j in jobs if j.status == JobStatus.IN_PROGRESS]
    qc_hold     = [j for j in jobs if j.status == JobStatus.QC_HOLD]
    queued      = [j for j in jobs if j.status == JobStatus.QUEUED]

    if len(completed) == len(jobs):
        status = JobStatus.COMPLETED
    elif qc_hold:
        status = JobStatus.QC_HOLD
    elif in_progress or completed:
        status = JobStatus.IN_PROGRESS
    else:
        status = JobStatus.QUEUED

    if status == JobStatus.COMPLETED:
        finished = [j.actual_completion_date or j.updated_at for j in jobs]
        finished = [f.date() if hasattr(f, 'date') else f for f in finished if f]
        date_label = 'Completed'
        date_value = max(finished) if finished else None
    else:
        date_label, date_value = 'Work orders raised', jobs[0].created_at

    planned = [j.planned_completion_date for j in jobs if j.planned_completion_date]

    if len(jobs) == 1:
        url = url_for('manufacturing.detail', job_id=jobs[0].id)
    else:
        url = url_for('manufacturing.index')

    return {
        'status_label': status,
        'url':          url,
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(status, JobStatus.LABELS)),
            ('Work orders', str(len(jobs))),
            ('Completed', str(len(completed))),
            ('In progress', str(len(in_progress)) if in_progress else None),
            ('QC hold', str(len(qc_hold)) if qc_hold else None),
            ('Queued', str(len(queued)) if queued else None),
            ('Planned completion', _d(max(planned)) if planned else None),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 12 — Delivery
# ------------------------------------------------------------------ #

def _delivery(tenant_id, order_ids):
    if not order_ids:
        return None
    deliveries = (Delivery.query
                  .filter(Delivery.tenant_id == tenant_id,
                          Delivery.order_id.in_(order_ids))
                  .order_by(Delivery.created_at)
                  .all())
    if not deliveries:
        return None

    statuses = {d.status for d in deliveries}
    if DeliveryStatus.DELIVERED_WITH_ISSUES in statuses:
        status = DeliveryStatus.DELIVERED_WITH_ISSUES
    elif DeliveryStatus.DISPATCHED in statuses:
        status = DeliveryStatus.DISPATCHED
    elif DeliveryStatus.PACKED in statuses:
        status = DeliveryStatus.PACKED
    else:
        status = DeliveryStatus.DELIVERED

    total_openings = ManufacturingJob.query.filter(
        ManufacturingJob.tenant_id == tenant_id,
        ManufacturingJob.order_id.in_(order_ids),
    ).count()
    delivered_openings = sum(
        len(d.items) for d in deliveries if d.status == DeliveryStatus.DELIVERED
    )
    dispatched = [d.dispatch_date for d in deliveries if d.dispatch_date]
    received   = [d.delivered_at for d in deliveries if d.delivered_at]
    last       = deliveries[-1]

    if status == DeliveryStatus.DELIVERED and received:
        date_label, date_value = 'Delivered', max(received)
    elif dispatched:
        date_label, date_value = 'Dispatched', min(dispatched)
    else:
        date_label, date_value = 'Packed', deliveries[0].packed_at or deliveries[0].created_at

    if len(deliveries) == 1:
        url = url_for('delivery.detail', delivery_id=deliveries[0].id)
    else:
        url = url_for('delivery.index')

    return {
        'status_label': status,
        'url':          url,
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(status, DeliveryStatus.LABELS)),
            ('Deliveries', str(len(deliveries))),
            ('Openings delivered', '%s of %s' % (delivered_openings, total_openings)),
            ('First dispatch', _dt(min(dispatched)) if dispatched else None),
            ('Last received', _dt(max(received)) if received else None),
            ('Vehicle', last.vehicle_ref),
            ('Received by', last.received_by),
            ('Damage / shortage', last.damage_shortage_notes),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 13 — Installation
# ------------------------------------------------------------------ #

def _installation(tenant_id, project_id):
    from . import installation_service
    from ...models.installation import InstallationStatus

    snap = installation_service.flow_snapshot(tenant_id, project_id)
    if not snap:
        return None

    insts = snap['installations']

    if not insts:
        return {
            'status_label': 'Ready to schedule',
            'url':          url_for('installation.index'),
            'date_label':   None,
            'date':         None,
            'tip': [
                ('Current status', 'Ready to schedule'),
                ('Delivered openings awaiting installation', str(snap['ready_to_schedule'])),
            ],
        }

    status = snap['status']
    first  = insts[0]
    last   = insts[-1]

    if status == InstallationStatus.COMPLETED and snap['fully_installed']:
        completed = [i.completed_at for i in insts if i.completed_at]
        date_label = 'Completed'
        date_value = max(completed) if completed else None
    else:
        date_label = 'Scheduled' if first.scheduled_date else 'Created'
        date_value = first.scheduled_date or first.created_at

    started  = [i.started_at for i in insts if i.started_at]
    signoffs = [i.customer_signoff_at for i in insts if i.customer_signoff_at]

    if len(insts) == 1:
        url = url_for('installation.detail', installation_id=first.id)
    else:
        url = url_for('installation.index')

    return {
        'status_label': status,
        'url':          url,
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip': [
            ('Current status', _status(status, InstallationStatus.LABELS)),
            ('Installations', str(len(insts))),
            ('Openings passed', '%s of %s' % (snap['passed'], snap['openings'])),
            ('Open snags', str(snap['open_snags']) if snap['open_snags'] else None),
            ('Scheduled', _d(first.scheduled_date)),
            ('Started', _dt(min(started)) if started else None),
            ('Team lead', last.team_lead_name),
            ('Customer sign-off', _dt(max(signoffs)) if signoffs else None),
            ('Signed by', last.signed_by if last.signed_by else None),
            ('Order fully installed', 'Yes' if snap['fully_installed'] else 'No'),
        ],
    }


# ------------------------------------------------------------------ #
#  Section 14 — AMC / Warranty
# ------------------------------------------------------------------ #

def _amc(tenant_id, project_id):
    from . import amc_service
    from ...models.amc import AmcStatus, WarrantyStatus

    snap = amc_service.flow_snapshot(tenant_id, project_id)
    if not snap:
        return None

    status   = snap['status']
    warranty = snap['warranties'][0]
    current  = snap['current']

    labels = dict(AmcStatus.LABELS)
    labels.update(WarrantyStatus.LABELS)

    if current and current.status == AmcStatus.ACTIVE and current.activated_at:
        date_label, date_value = 'AMC activated', current.activated_at
    elif current and current.status == AmcStatus.OFFERED and current.offered_at:
        date_label, date_value = 'AMC offered', current.offered_at
    else:
        date_label, date_value = 'Warranty from', warranty.warranty_start_date

    url = (url_for('amc.detail', contract_id=current.id) if current
           else url_for('amc.index'))

    tip = [
        ('Current status', _status(status, labels)),
        ('Warranty', warranty.warranty_number),
        ('Warranty period', '%s → %s' % (_d(warranty.warranty_start_date),
                                         _d(warranty.warranty_end_date))),
        ('Warranty days left', str(warranty.days_remaining) if warranty.in_period else 'Ended'),
    ]
    if current:
        tip += [
            ('AMC', current.amc_number),
            ('AMC plan', '%s · %s visit(s)/yr' % (current.plan_tier, current.visits_per_year)),
            ('AMC annual fee', _money(current.annual_fee)),
            ('AMC term', ('%s → %s' % (_d(current.amc_start_date), _d(current.amc_end_date)))
                         if current.amc_start_date and current.amc_end_date else None),
            ('AMC days to expiry', str(current.days_to_expiry)
                                   if current.status == AmcStatus.ACTIVE and current.days_to_expiry is not None
                                   else None),
            ('Signed by', current.signed_by),
        ]
    tip += [
        ('Service tickets', '%s open · %s resolved · %s total' % (
            snap['tickets_open'], snap['tickets_resolved'], snap['tickets_total'])
            if snap['tickets_total'] else None),
    ]

    return {
        'status_label': status,
        'url':          url,
        'date_label':   date_label,
        'date':         _d(date_value),
        'tip':          tip,
    }


# ------------------------------------------------------------------ #
#  Public entry point
# ------------------------------------------------------------------ #

def build_downstream(tenant_id: int, project_id: int | None) -> dict:
    """Stage data for Quotation → Installation. One failing stage never blanks the rest."""
    if not project_id:
        return {}

    orders = (Order.query
              .filter_by(tenant_id=tenant_id, project_id=project_id)
              .order_by(Order.created_at)
              .all())
    order_ids = [o.id for o in orders]

    builders = [
        ('quotation',       lambda: _quotation(tenant_id, project_id)),
        ('order',           lambda: _order(orders)),
        ('advance_payment', lambda: _advance_payment(tenant_id, order_ids)),
        ('payment_journey', lambda: _payment_journey(tenant_id, order_ids)),
        ('manufacturing',   lambda: _manufacturing(tenant_id, order_ids)),
        ('delivery',        lambda: _delivery(tenant_id, order_ids)),
        ('installation',    lambda: _installation(tenant_id, project_id)),
        ('amc',             lambda: _amc(tenant_id, project_id)),
    ]

    result = {}
    for key, build in builders:
        try:
            data = build()
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Flow stage "%s" error: %s', key, exc)
            continue
        if data:
            result[key] = data
    return result
