from datetime import datetime, date

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStatus, PaymentStage
from ...models.manufacturing_job import ManufacturingJob, JobStatus
from ...models.delivery import Delivery, DeliveryItem, DeliveryStatus


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_delivery(tenant_id: int, delivery_id: int) -> Delivery | None:
    return Delivery.query.filter_by(id=delivery_id, tenant_id=tenant_id).first()


def list_for_order(tenant_id: int, order_id: int) -> list[Delivery]:
    from sqlalchemy import asc
    return (Delivery.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(Delivery.created_at))
            .all())


def list_deliveries(tenant_id: int, status: str | None = None) -> list[Delivery]:
    from sqlalchemy import desc
    q = Delivery.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(Delivery.created_at)).all()


def delivered_opening_ids(tenant_id: int, order_id: int) -> set[int]:
    ids = set()
    for d in list_for_order(tenant_id, order_id):
        for item in d.items:
            ids.add(item.opening_id)
    return ids


def pending_openings(tenant_id: int, order_id: int) -> list[ManufacturingJob]:
    """Completed manufacturing jobs whose opening is not yet in any delivery."""
    taken = delivered_opening_ids(tenant_id, order_id)
    jobs = (ManufacturingJob.query
            .filter_by(tenant_id=tenant_id, order_id=order_id, status=JobStatus.COMPLETED)
            .all())
    return [j for j in jobs if j.opening_id not in taken]


def is_order_fully_delivered(tenant_id: int, order_id: int) -> bool:
    jobs = ManufacturingJob.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()
    if not jobs:
        return False
    deliveries = [d for d in list_for_order(tenant_id, order_id)
                  if d.status == DeliveryStatus.DELIVERED]
    delivered = set()
    for d in deliveries:
        for item in d.items:
            delivered.add(item.opening_id)
    return all(j.opening_id in delivered for j in jobs)


# ------------------------------------------------------------------ #
#  Guards
# ------------------------------------------------------------------ #

def _require_order(tenant_id: int, order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.CONFIRMED:
        raise ValueError(f'Order must be ORDER-CONFIRMED; status={order.status}')
    return order


def _require_payment_clear(tenant_id: int, order_id: int) -> None:
    """Pre-Dispatch milestone (if invoiced) must be received and no hold may be active."""
    payments = Payment.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()

    for p in payments:
        if p.hold_flag or p.status == PaymentStatus.HOLD_APPLIED:
            raise ValueError(
                f'Dispatch is blocked: payment {p.payment_number} has a hold applied.'
            )

    for p in payments:
        if p.payment_stage == PaymentStage.PRE_DISPATCH and \
                p.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
            raise ValueError(
                'Pre-Dispatch payment must be PAY-RECEIVED before dispatch.'
            )


def _get_or_raise(tenant_id: int, delivery_id: int) -> Delivery:
    delivery = get_delivery(tenant_id, delivery_id)
    if not delivery:
        raise LookupError('Delivery not found')
    return delivery


# ------------------------------------------------------------------ #
#  Pack  →  DEL-PACKED
# ------------------------------------------------------------------ #

def create_delivery(
    tenant_id:               int,
    order_id:                int,
    created_by:              int,
    opening_ids:             list[int] | None = None,
    delivery_address:        str | None = None,
    site_contact_name:       str | None = None,
    site_contact_phone:      str | None = None,
    scheduled_dispatch_date: date | None = None,
    package_labels:          dict[int, str] | None = None,
) -> Delivery:
    order = _require_order(tenant_id, order_id)

    available = pending_openings(tenant_id, order_id)
    if not available:
        raise ValueError('No manufactured openings are pending delivery for this order.')

    available_map = {j.opening_id: j for j in available}
    if opening_ids:
        invalid = [oid for oid in opening_ids if oid not in available_map]
        if invalid:
            raise ValueError(
                f'Openings not ready for delivery (not MFG-COMPLETED or already packed): {invalid}'
            )
        selected = [available_map[oid] for oid in opening_ids]
    else:
        selected = available

    now = datetime.utcnow()
    delivery = Delivery(
        tenant_id               = tenant_id,
        order_id                = order.id,
        delivery_number         = Delivery.generate_number(tenant_id),
        challan_number          = Delivery.generate_challan_number(tenant_id),
        status                  = DeliveryStatus.PACKED,
        delivery_address        = delivery_address,
        site_contact_name       = site_contact_name,
        site_contact_phone      = site_contact_phone,
        scheduled_dispatch_date = scheduled_dispatch_date,
        packed_at               = now,
        packed_by               = created_by,
        created_by              = created_by,
        created_at              = now,
        updated_at              = now,
    )
    db.session.add(delivery)
    db.session.flush()

    labels = package_labels or {}
    for job in selected:
        db.session.add(DeliveryItem(
            tenant_id            = tenant_id,
            delivery_id          = delivery.id,
            opening_id           = job.opening_id,
            manufacturing_job_id = job.id,
            package_label        = labels.get(job.opening_id) or f'OPN-{job.opening_id}',
            package_count        = 1,
            created_at           = now,
        ))

    db.session.commit()
    return delivery


# ------------------------------------------------------------------ #
#  Dispatch  →  DEL-DISPATCHED
# ------------------------------------------------------------------ #

def dispatch_delivery(
    tenant_id:        int,
    delivery_id:      int,
    vehicle_ref:      str,
    transporter_name: str | None = None,
    driver_name:      str | None = None,
    driver_phone:     str | None = None,
    assigned_to:      int | None = None,
) -> Delivery:
    delivery = _get_or_raise(tenant_id, delivery_id)
    if delivery.status != DeliveryStatus.PACKED:
        raise ValueError(f'Delivery must be DEL-PACKED to dispatch; status={delivery.status}')
    if not vehicle_ref:
        raise ValueError('Vehicle reference is required to dispatch.')
    if not delivery.items:
        raise ValueError('Delivery has no items.')

    _require_payment_clear(tenant_id, delivery.order_id)

    now = datetime.utcnow()
    delivery.status           = DeliveryStatus.DISPATCHED
    delivery.dispatch_date    = now
    delivery.vehicle_ref      = vehicle_ref
    delivery.transporter_name = transporter_name
    delivery.driver_name      = driver_name
    delivery.driver_phone     = driver_phone
    if assigned_to is not None:
        delivery.assigned_to  = assigned_to
    delivery.updated_at       = now
    db.session.commit()
    return delivery


# ------------------------------------------------------------------ #
#  Receive at site  →  DEL-DELIVERED / DEL-DELIVERED_WITH_ISSUES
# ------------------------------------------------------------------ #

def confirm_delivery(
    tenant_id:             int,
    delivery_id:           int,
    received_by:           str,
    item_issues:           list[dict] | None = None,
    damage_shortage_notes: str | None = None,
    pod_file_path:         str | None = None,
) -> Delivery:
    """
    item_issues: [{'opening_id': int, 'is_damaged': bool, 'is_short': bool, 'issue_notes': str}, ...]
    """
    delivery = _get_or_raise(tenant_id, delivery_id)
    if delivery.status != DeliveryStatus.DISPATCHED:
        raise ValueError(f'Delivery must be DEL-DISPATCHED to confirm receipt; status={delivery.status}')
    if not received_by:
        raise ValueError('Received-by name is required.')

    issue_map = {i['opening_id']: i for i in (item_issues or []) if i.get('opening_id') is not None}
    for item in delivery.items:
        data = issue_map.get(item.opening_id)
        if data:
            item.is_damaged     = bool(data.get('is_damaged'))
            item.is_short       = bool(data.get('is_short'))
            item.issue_notes    = data.get('issue_notes')
            item.issue_resolved = False

    now = datetime.utcnow()
    delivery.received_by           = received_by
    delivery.delivered_at          = now
    delivery.damage_shortage_notes = damage_shortage_notes
    if pod_file_path:
        delivery.pod_file_path     = pod_file_path
    delivery.status = (
        DeliveryStatus.DELIVERED_WITH_ISSUES
        if any(i.has_issue for i in delivery.items)
        else DeliveryStatus.DELIVERED
    )
    delivery.updated_at = now
    db.session.commit()
    return delivery


# ------------------------------------------------------------------ #
#  Resolve issues  →  DEL-DELIVERED
# ------------------------------------------------------------------ #

def resolve_item_issue(tenant_id: int, delivery_id: int, item_id: int,
                       resolution_notes: str | None = None) -> Delivery:
    delivery = _get_or_raise(tenant_id, delivery_id)
    if delivery.status != DeliveryStatus.DELIVERED_WITH_ISSUES:
        raise ValueError(
            f'Delivery must be DEL-DELIVERED_WITH_ISSUES to resolve issues; status={delivery.status}'
        )

    item = next((i for i in delivery.items if i.id == item_id), None)
    if not item:
        raise LookupError('Delivery item not found')
    if not item.has_issue:
        raise ValueError('Item has no recorded issue.')

    item.issue_resolved = True
    if resolution_notes:
        item.issue_notes = f'{item.issue_notes or ""}\nResolved: {resolution_notes}'.strip()

    now = datetime.utcnow()
    if not delivery.has_open_issues:
        delivery.status = DeliveryStatus.DELIVERED
    delivery.updated_at = now
    db.session.commit()
    return delivery


def resolve_all_issues(tenant_id: int, delivery_id: int,
                       resolution_notes: str | None = None) -> Delivery:
    delivery = _get_or_raise(tenant_id, delivery_id)
    if delivery.status != DeliveryStatus.DELIVERED_WITH_ISSUES:
        raise ValueError(
            f'Delivery must be DEL-DELIVERED_WITH_ISSUES to resolve issues; status={delivery.status}'
        )

    for item in delivery.items:
        if item.has_issue and not item.issue_resolved:
            item.issue_resolved = True
            if resolution_notes:
                item.issue_notes = f'{item.issue_notes or ""}\nResolved: {resolution_notes}'.strip()

    delivery.status     = DeliveryStatus.DELIVERED
    delivery.updated_at = datetime.utcnow()
    db.session.commit()
    return delivery


# ------------------------------------------------------------------ #
#  Per-opening progress (partial manufacturing / partial delivery)
# ------------------------------------------------------------------ #

def opening_progress(tenant_id: int, order_id: int) -> dict:
    """
    One row per opening on the order showing where it is right now:
    in_production → ready → packed → in_transit → delivered (or issue).
    Lets the user pack and dispatch finished openings without waiting for
    the rest of the order.
    """
    from sqlalchemy import asc

    jobs = (ManufacturingJob.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(ManufacturingJob.id)).all())

    item_map = {}
    for d in list_for_order(tenant_id, order_id):
        for item in d.items:
            item_map[item.opening_id] = (d, item)

    rows = []
    for j in jobs:
        delivery = item = None
        found = item_map.get(j.opening_id)
        if found:
            delivery, item = found
            if delivery.status == DeliveryStatus.PACKED:
                state, label = 'packed', 'Packed'
            elif delivery.status == DeliveryStatus.DISPATCHED:
                state, label = 'in_transit', 'In transit'
            elif item.has_issue and not item.issue_resolved:
                state, label = 'issue', 'Delivered — issue open'
            else:
                state, label = 'delivered', 'Delivered'
        elif j.status == JobStatus.COMPLETED:
            state, label = 'ready', 'Ready to pack'
        elif j.status == JobStatus.QUEUED:
            state, label = 'in_production', 'Queued for production'
        elif j.status == JobStatus.QC_HOLD:
            state, label = 'in_production', 'QC hold — %s' % j.stage_label
        else:
            state, label = 'in_production', 'In production — %s' % j.stage_label

        rows.append({
            'opening':  j.opening,
            'job':      j,
            'delivery': delivery,
            'item':     item,
            'state':    state,
            'label':    label,
        })

    def count(*states):
        return sum(1 for r in rows if r['state'] in states)

    total = len(rows)
    summary = {
        'total':         total,
        'delivered':     count('delivered'),
        'in_transit':    count('in_transit'),
        'packed':        count('packed'),
        'ready':         count('ready'),
        'in_production': count('in_production'),
        'issue':         count('issue'),
    }
    summary['pending'] = total - summary['delivered']
    return {'rows': rows, 'summary': summary}


# ------------------------------------------------------------------ #
#  Installation gate
# ------------------------------------------------------------------ #

def is_ready_for_installation(tenant_id: int, order_id: int) -> bool:
    """DEL-DELIVERED (issues resolved) for every manufactured opening → Installation."""
    return is_order_fully_delivered(tenant_id, order_id)
