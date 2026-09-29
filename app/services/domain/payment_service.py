import json
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStatus, PaymentStage, ReleaseMode
from ...models.payment_receipt import PaymentReceipt
from ...models.order_unit_release import OrderUnitRelease, UnitReleaseStatus
from ...models.window import Window

DEFAULT_ADVANCE_PCT = Decimal('50')

# Share of the (100 - advance %) balance carried by each later stage.
LATER_STAGE_WEIGHTS = {
    PaymentStage.PRE_DISPATCH:    Decimal('70'),
    PaymentStage.ON_INSTALLATION: Decimal('20'),
    PaymentStage.RETENTION:       Decimal('10'),
}


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def stage_percentages(advance_pct) -> dict:
    """Percent of order value billed at every stage; always sums to 100."""
    adv       = Decimal(str(advance_pct))
    remaining = Decimal('100') - adv
    total_w   = sum(LATER_STAGE_WEIGHTS.values())
    out = {PaymentStage.ADVANCE: adv}
    stages = list(LATER_STAGE_WEIGHTS)
    running = adv
    for i, st in enumerate(stages):
        if i == len(stages) - 1:
            out[st] = Decimal('100') - running
        else:
            out[st] = (remaining * LATER_STAGE_WEIGHTS[st] / total_w).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            running += out[st]
    return out


def get_stage_payment(tenant_id: int, order_id: int, stage: str) -> Payment | None:
    return (Payment.query
            .filter_by(tenant_id=tenant_id, order_id=order_id, payment_stage=stage)
            .order_by(Payment.id.asc())
            .first())


def stage_amount(order: Order, advance_pct, stage: str) -> Decimal:
    pct = stage_percentages(advance_pct)[stage]
    return _q(order_basis(order) * pct / Decimal('100'))


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_payment(tenant_id: int, payment_id: int) -> Payment | None:
    db.session.expire_all()
    return Payment.query.filter_by(id=payment_id, tenant_id=tenant_id).first()


def list_for_order(tenant_id: int, order_id: int) -> list[Payment]:
    from sqlalchemy import asc
    return (Payment.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(Payment.created_at))
            .all())


def list_payments(tenant_id: int, status: str | None = None) -> list[Payment]:
    from sqlalchemy import desc
    q = Payment.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(Payment.created_at)).all()


def get_advance_for_order(tenant_id: int, order_id: int) -> Payment | None:
    return Payment.query.filter_by(
        tenant_id=tenant_id, order_id=order_id, payment_stage=PaymentStage.ADVANCE
    ).first()


def is_advance_received(tenant_id: int, order_id: int) -> bool:
    advance = get_advance_for_order(tenant_id, order_id)
    return bool(advance and advance.status == PaymentStatus.RECEIVED)


def outstanding_balance(tenant_id: int, order_id: int) -> Decimal:
    payments = list_for_order(tenant_id, order_id)
    total = Decimal('0')
    for p in payments:
        if p.status != PaymentStatus.CLOSED:
            total += (p.invoice_amount or 0) - (p.amount_received or 0)
    return total


def list_receipts(tenant_id: int, payment_id: int) -> list[PaymentReceipt]:
    return (PaymentReceipt.query
            .filter_by(tenant_id=tenant_id, payment_id=payment_id)
            .order_by(PaymentReceipt.received_at.asc(), PaymentReceipt.id.asc())
            .all())


def list_unit_releases(tenant_id: int, payment_id: int) -> list[OrderUnitRelease]:
    return (OrderUnitRelease.query
            .filter_by(tenant_id=tenant_id, payment_id=payment_id)
            .order_by(OrderUnitRelease.priority.asc(), OrderUnitRelease.id.asc())
            .all())


def order_basis(order: Order) -> Decimal:
    """Order value (incl. tax and charges) used to size the advance."""
    if order.total_amount:
        return _q(order.total_amount)
    q = getattr(order, 'quotation', None)
    if q is not None and q.grand_total:
        return _q(q.grand_total)
    return Decimal('0.00')


def default_advance_amount(order: Order, pct=DEFAULT_ADVANCE_PCT) -> Decimal:
    return _q(order_basis(order) * Decimal(str(pct)) / Decimal('100'))


def unit_release_summary(tenant_id: int, order_id: int) -> dict:
    advance = get_advance_for_order(tenant_id, order_id)
    if not advance or not advance.is_unit_wise:
        return {'unit_wise': False, 'total': 0, 'released': 0, 'pending': 0}
    rows = list_unit_releases(tenant_id, advance.id)
    released = sum(1 for r in rows if r.is_released)
    return {
        'unit_wise': True,
        'total':     len(rows),
        'released':  released,
        'pending':   len(rows) - released,
    }


def released_window_ids(tenant_id: int, order_id: int) -> list[int] | None:
    """
    Windows / doors cleared for manufacturing.
    None  -> whole-order mode (no per-unit filter; use the advance status).
    list  -> unit-wise mode; only these window ids may be manufactured.
    """
    advance = get_advance_for_order(tenant_id, order_id)
    if not advance or not advance.is_unit_wise:
        return None
    return [
        r.window_id for r in list_unit_releases(tenant_id, advance.id)
        if r.is_released and r.window_id
    ]


def is_order_released_for_manufacturing(tenant_id: int, order_id: int) -> bool:
    advance = get_advance_for_order(tenant_id, order_id)
    if not advance:
        return False
    if advance.is_unit_wise:
        return any(r.is_released for r in list_unit_releases(tenant_id, advance.id))
    return advance.status in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)


# ------------------------------------------------------------------ #
#  Guard: order must be CONFIRMED before invoicing
# ------------------------------------------------------------------ #

def _require_confirmed_order(tenant_id: int, order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.CONFIRMED:
        raise ValueError(
            f'Order must be ORDER-CONFIRMED before raising a payment milestone; status={order.status}'
        )
    return order


def _validate_policy(release_mode: str, advance_pct) -> tuple[str, Decimal]:
    if release_mode not in ReleaseMode.ALL:
        raise ValueError(f'Invalid release mode: {release_mode}')
    try:
        pct = Decimal(str(advance_pct))
    except Exception:
        raise ValueError('Advance % must be a number.')
    if pct <= 0 or pct > 100:
        raise ValueError('Advance % must be between 1 and 100.')
    return release_mode, pct


# ------------------------------------------------------------------ #
#  Unit ledger (unit-wise release)
# ------------------------------------------------------------------ #

def _unit_lines(order: Order) -> list[dict]:
    q = getattr(order, 'quotation', None)
    lines = []
    if q is not None:
        for item in q.line_items:
            if item.get('window_id'):
                lines.append(item)
    return lines


def build_unit_ledger(payment: Payment) -> list[OrderUnitRelease]:
    """Create (once) one release row per window/door on the order."""
    existing = list_unit_releases(payment.tenant_id, payment.id)
    if existing:
        return existing

    order = payment.order
    lines = _unit_lines(order)
    if not lines:
        raise ValueError('Unit-wise release needs window / door lines on the quotation.')

    basis = Decimal(str(payment.order_total_basis or order_basis(order)))
    if basis <= 0:
        raise ValueError('Order value is zero; cannot size unit-wise advance.')
    ratio = Decimal(str(payment.invoice_amount)) / basis

    sum_lines = sum((Decimal(str(l.get('amount') or 0)) for l in lines), Decimal('0'))
    if sum_lines <= 0:
        raise ValueError('Quotation unit lines have no value.')

    win_ids = [l['window_id'] for l in lines]
    windows = {
        w.id: w for w in Window.query.filter(
            Window.id.in_(win_ids), Window.tenant_id == payment.tenant_id).all()
    }

    def _unit_type(w) -> str:
        try:
            if w is not None and getattr(w, 'design_json', None):
                return 'door' if json.loads(w.design_json).get('unitType') == 'door' else 'window'
        except (ValueError, TypeError, AttributeError):
            pass
        return 'window'

    rows = []
    for l in lines:
        w = windows.get(l['window_id'])
        share = Decimal(str(l.get('amount') or 0)) / sum_lines
        gross = _q(basis * share)
        rows.append({
            'window_id': l['window_id'],
            'label':     l.get('label') or (w.label if w else f"Unit {l['window_id']}"),
            'unit_type': _unit_type(w),
            'gross':     gross,
            'required':  _q(gross * ratio),
            'seq':       (w.sequence_order if w is not None and w.sequence_order is not None else 0),
        })

    # default priority: doors first, then sequence
    rows.sort(key=lambda r: (0 if r['unit_type'] == 'door' else 1, r['seq'], r['window_id']))

    # later stages follow the priority already set on the advance ledger
    if payment.payment_stage != PaymentStage.ADVANCE:
        adv = get_advance_for_order(payment.tenant_id, order.id)
        if adv is not None:
            adv_prio = {r.window_id: r.priority for r in list_unit_releases(adv.tenant_id, adv.id)}
            rows.sort(key=lambda r: adv_prio.get(r['window_id'], 10 ** 6))

    stage_pct = (Decimal(str(payment.advance_pct))
                 if payment.payment_stage == PaymentStage.ADVANCE
                 else _q(Decimal(str(payment.invoice_amount)) / basis * Decimal('100')))

    # make required amounts add up exactly to the advance invoice
    diff = _q(payment.invoice_amount) - sum((r['required'] for r in rows), Decimal('0'))
    if rows and diff != 0:
        rows[-1]['required'] = _q(rows[-1]['required'] + diff)

    created = []
    for i, r in enumerate(rows):
        ur = OrderUnitRelease(
            tenant_id        = payment.tenant_id,
            order_id         = order.id,
            payment_id       = payment.id,
            window_id        = r['window_id'],
            stage            = payment.payment_stage,
            stage_pct        = stage_pct,
            label            = r['label'],
            unit_type        = r['unit_type'],
            line_amount      = r['gross'],
            required_advance = r['required'],
            allocated_amount = Decimal('0'),
            priority         = i * 10,
            status           = UnitReleaseStatus.PENDING,
        )
        db.session.add(ur)
        created.append(ur)
    db.session.commit()
    return created


def allocate_advance(payment: Payment) -> list[OrderUnitRelease]:
    """
    Allocate the advance received to units in priority order.
    A unit is released only when its full required advance is covered.
    Released units stay released. Leftover money that cannot cover the next
    unit is shown on that unit as a partial allocation and never releases it.
    """
    rows = list_unit_releases(payment.tenant_id, payment.id)
    if not rows:
        return []

    remaining = _q(payment.amount_received)
    now = datetime.utcnow()
    newly_released = []

    # released units keep their money
    for r in rows:
        if r.status == UnitReleaseStatus.RELEASED:
            r.allocated_amount = r.required_advance
            remaining -= _q(r.required_advance)
    if remaining < 0:
        remaining = Decimal('0.00')

    for r in rows:
        if r.status == UnitReleaseStatus.RELEASED:
            continue
        req = _q(r.required_advance)
        if remaining >= req and req > 0:
            r.allocated_amount = req
            r.status           = UnitReleaseStatus.RELEASED
            r.released_at      = now
            remaining         -= req
            newly_released.append(r)
        elif remaining > 0:
            r.allocated_amount = remaining
            r.status           = UnitReleaseStatus.PARTIAL
            remaining          = Decimal('0.00')
        else:
            r.allocated_amount = Decimal('0.00')
            r.status           = UnitReleaseStatus.PENDING

    db.session.commit()
    if newly_released and payment.payment_stage == PaymentStage.ADVANCE:
        _release_units_to_manufacturing(payment.order, newly_released)
    return rows


allocate_receipt = allocate_advance


def reorder_units(tenant_id: int, payment_id: int, ordered_unit_ids: list[int]) -> Payment:
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if not payment.is_unit_wise:
        raise ValueError('Priority applies only to unit-wise release.')
    rows = {r.id: r for r in list_unit_releases(tenant_id, payment_id)}
    seen = [uid for uid in ordered_unit_ids if uid in rows]
    rest = [uid for uid in rows if uid not in seen]
    for i, uid in enumerate(seen + rest):
        rows[uid].priority = i * 10
    db.session.commit()
    allocate_advance(payment)
    return payment


def update_release_policy(
    tenant_id:    int,
    payment_id:   int,
    release_mode: str,
    advance_pct=None,
) -> Payment:
    """Change release mode / advance % on the advance invoice (before any receipt)."""
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.payment_stage != PaymentStage.ADVANCE:
        raise ValueError('Release policy applies only to the Advance milestone.')
    if (payment.amount_received or 0) > 0:
        raise ValueError('Release policy cannot change after a receipt is recorded.')
    if any(p.id != payment.id for p in list_for_order(tenant_id, payment.order_id)):
        raise ValueError('Release policy cannot change after later-stage invoices are raised.')

    pct_in = advance_pct if advance_pct not in (None, '') else payment.advance_pct
    mode, pct = _validate_policy(release_mode, pct_in)

    basis = Decimal(str(payment.order_total_basis or order_basis(payment.order)))
    if basis > 0 and pct != Decimal(str(payment.advance_pct)):
        payment.invoice_amount = _q(basis * pct / Decimal('100'))
        payment.order_total_basis = basis

    old_mode = payment.release_mode
    payment.release_mode = mode
    payment.advance_pct  = pct
    payment.updated_at   = datetime.utcnow()
    db.session.commit()

    # rebuild unit ledger when needed
    for r in list_unit_releases(tenant_id, payment.id):
        db.session.delete(r)
    db.session.commit()
    if mode == ReleaseMode.UNIT_WISE:
        build_unit_ledger(payment)
    return payment


# ------------------------------------------------------------------ #
#  Raise invoice  →  PAY-INVOICED
# ------------------------------------------------------------------ #

def raise_invoice(
    tenant_id:      int,
    order_id:       int,
    raised_by:      int,
    payment_stage:  str = PaymentStage.ADVANCE,
    invoice_amount: float = 0.0,
    due_date:       date | None = None,
    release_mode:   str = ReleaseMode.WHOLE_ORDER,
    advance_pct:    float = 50.0,
) -> Payment:
    order = _require_confirmed_order(tenant_id, order_id)

    if payment_stage not in PaymentStage.ALL:
        raise ValueError(f'Invalid payment stage: {payment_stage}')

    if payment_stage == PaymentStage.ADVANCE and get_advance_for_order(tenant_id, order_id):
        raise ValueError('An advance invoice already exists for this order.')

    basis = order_basis(order)
    mode  = ReleaseMode.WHOLE_ORDER
    pct   = DEFAULT_ADVANCE_PCT

    if payment_stage == PaymentStage.ADVANCE:
        mode, pct = _validate_policy(release_mode, advance_pct)
        if not invoice_amount or Decimal(str(invoice_amount)) <= 0:
            invoice_amount = default_advance_amount(order, pct)
        elif basis > 0:
            pct = _q(Decimal(str(invoice_amount)) / basis * Decimal('100'))
            if pct > 100:
                raise ValueError('Advance cannot exceed the order value.')
    else:
        if get_stage_payment(tenant_id, order_id, payment_stage):
            raise ValueError(f'A {payment_stage} invoice already exists for this order.')
        adv = get_advance_for_order(tenant_id, order_id)
        if adv is None:
            raise ValueError('Raise the advance invoice before later milestones.')
        mode = adv.release_mode
        pct  = adv.advance_pct
        if not invoice_amount or Decimal(str(invoice_amount)) <= 0:
            invoice_amount = stage_amount(order, adv.advance_pct, payment_stage)
        already = sum((Decimal(str(p.invoice_amount or 0))
                       for p in list_for_order(tenant_id, order_id)), Decimal('0'))
        if basis > 0 and already + Decimal(str(invoice_amount)) > basis + Decimal('0.01'):
            raise ValueError('Total invoiced would exceed the order value.')

    if not invoice_amount or Decimal(str(invoice_amount)) <= 0:
        raise ValueError('Invoice amount must be greater than zero.')

    payment = Payment(
        tenant_id         = tenant_id,
        order_id          = order.id,
        payment_number    = Payment.generate_number(tenant_id),
        payment_stage     = payment_stage,
        status            = PaymentStatus.INVOICED,
        invoice_amount    = _q(invoice_amount),
        amount_received   = Decimal('0'),
        due_date          = due_date,
        release_mode      = mode,
        advance_pct       = pct,
        order_total_basis = basis if basis > 0 else None,
        raised_by         = raised_by,
        created_at        = datetime.utcnow(),
        updated_at        = datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()

    if mode == ReleaseMode.UNIT_WISE:
        try:
            build_unit_ledger(payment)
        except ValueError:
            db.session.delete(payment)
            db.session.commit()
            raise
    return payment


# ------------------------------------------------------------------ #
#  Record receipt  →  PAY-PARTIAL / PAY-RECEIVED
# ------------------------------------------------------------------ #

def record_receipt(
    tenant_id:        int,
    payment_id:       int,
    amount_received:  float,
    payment_mode:     str,
    transaction_ref:  str | None = None,
    recorded_by:      int | None = None,
    notes:            str | None = None,
) -> Payment:
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.status in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
        raise ValueError(f'Payment is already settled; status={payment.status}')
    if not amount_received or Decimal(str(amount_received)) <= 0:
        raise ValueError('Amount received must be greater than zero.')

    now    = datetime.utcnow()
    amount = _q(amount_received)

    db.session.add(PaymentReceipt(
        tenant_id       = tenant_id,
        payment_id      = payment.id,
        amount          = amount,
        payment_mode    = payment_mode,
        transaction_ref = transaction_ref,
        received_at     = now,
        notes           = notes,
        recorded_by     = recorded_by,
        created_at      = now,
    ))

    new_total = (payment.amount_received or Decimal('0')) + amount
    payment.amount_received = new_total
    payment.payment_mode    = payment_mode
    payment.transaction_ref = transaction_ref
    payment.received_at     = now
    payment.hold_flag       = False

    if new_total >= (payment.invoice_amount or Decimal('0')):
        payment.status = PaymentStatus.RECEIVED
    else:
        payment.status = PaymentStatus.PARTIAL

    payment.updated_at = now
    db.session.commit()

    if payment.is_unit_wise:
        allocate_receipt(payment)
    elif payment.payment_stage == PaymentStage.ADVANCE and payment.status == PaymentStatus.RECEIVED:
        _release_to_manufacturing(payment.order)

    close_if_settled(tenant_id, payment.order_id)
    return payment


def _queue_manufacturing(order: Order) -> None:
    """Queue work orders for every unit currently cleared and not yet queued."""
    from . import manufacturing_service
    try:
        manufacturing_service.generate_jobs_for_order(order.tenant_id, order.id)
    except (ValueError, LookupError):
        db.session.rollback()


def _release_to_manufacturing(order: Order) -> None:
    """Whole-order advance PAY-RECEIVED clears every unit for Manufacturing."""
    _queue_manufacturing(order)


def _release_units_to_manufacturing(order: Order, units: list[OrderUnitRelease]) -> None:
    """Units whose advance is fully covered are cleared and queued for Manufacturing."""
    _queue_manufacturing(order)


# ------------------------------------------------------------------ #
#  Per-unit balances (auto-recalculated from the stage ledgers)
# ------------------------------------------------------------------ #

def unit_balances(tenant_id: int, order_id: int) -> list[dict]:
    """One dict per unit: total value, paid, balance, % paid and status per stage."""
    rows = (OrderUnitRelease.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(OrderUnitRelease.priority.asc(), OrderUnitRelease.id.asc())
            .all())
    units: dict = {}
    for r in rows:
        u = units.setdefault(r.window_id, {
            'window_id':   r.window_id,
            'label':       r.label,
            'unit_type':   r.unit_type,
            'total':       Decimal('0'),
            'paid':        Decimal('0'),
            'stages':      {},
        })
        u['total'] = max(u['total'], _q(r.line_amount))
        u['paid']  += _q(r.allocated_amount)
        u['stages'][r.stage] = {
            'required':  float(r.required_advance or 0),
            'allocated': float(r.allocated_amount or 0),
            'shortfall': float(r.shortfall or 0),
            'pct':       r.pct_covered,
            'status':    r.status,
        }
    out = []
    for u in units.values():
        total, paid = u['total'], u['paid']
        balance = total - paid
        u['balance']    = float(balance)
        u['pct_paid']   = float((paid / total * 100).quantize(Decimal('0.01'))) if total > 0 else 0.0
        u['fully_paid'] = total > 0 and balance <= 0
        u['total']      = float(total)
        u['paid']       = float(paid)
        out.append(u)
    return out


def order_payment_summary(tenant_id: int, order_id: int) -> dict:
    payments = list_for_order(tenant_id, order_id)
    invoiced = sum((Decimal(str(p.invoice_amount or 0)) for p in payments), Decimal('0'))
    received = sum((Decimal(str(p.amount_received or 0)) for p in payments), Decimal('0'))
    order    = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    basis    = order_basis(order) if order else Decimal('0')
    return {
        'basis':        float(basis),
        'invoiced':     float(invoiced),
        'received':     float(received),
        'balance':      float(basis - received),
        'pct_received': float((received / basis * 100).quantize(Decimal('0.01'))) if basis > 0 else 0.0,
    }


# ------------------------------------------------------------------ #
#  Auto-invoicing of later stages (Pre-Dispatch -> On-Installation -> Retention)
# ------------------------------------------------------------------ #

def _stage_trigger_met(tenant_id: int, order_id: int, stage: str) -> bool:
    from ...models.manufacturing_job import ManufacturingJob, JobStatus
    from ...models.delivery import Delivery, DeliveryStatus
    from . import installation_service

    if stage == PaymentStage.PRE_DISPATCH:
        return ManufacturingJob.query.filter_by(
            tenant_id=tenant_id, order_id=order_id, status=JobStatus.COMPLETED).first() is not None
    if stage == PaymentStage.ON_INSTALLATION:
        return Delivery.query.filter(
            Delivery.tenant_id == tenant_id, Delivery.order_id == order_id,
            Delivery.status.in_([DeliveryStatus.DELIVERED, DeliveryStatus.DELIVERED_WITH_ISSUES])
        ).first() is not None
    if stage == PaymentStage.RETENTION:
        return installation_service.is_order_fully_installed(tenant_id, order_id)
    return False


def auto_invoice_stages(tenant_id: int, order_id: int, raised_by: int | None = None,
                        due_date: date | None = None, force_next: bool = False) -> list[Payment]:
    """
    Raise every later-stage invoice whose trigger is met and which does not exist yet.
    force_next=True raises the next missing stage regardless of trigger.
    """
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order or order.status != OrderStatus.CONFIRMED:
        return []
    if get_advance_for_order(tenant_id, order_id) is None:
        return []

    raised = []
    for stage in (PaymentStage.PRE_DISPATCH, PaymentStage.ON_INSTALLATION, PaymentStage.RETENTION):
        if get_stage_payment(tenant_id, order_id, stage):
            continue
        if force_next or _stage_trigger_met(tenant_id, order_id, stage):
            raised.append(raise_invoice(
                tenant_id=tenant_id, order_id=order_id, raised_by=raised_by,
                payment_stage=stage, invoice_amount=0.0, due_date=due_date))
            if force_next:
                break
        else:
            break
    return raised


def auto_invoice_all(tenant_id: int | None = None) -> int:
    q = Order.query.filter_by(status=OrderStatus.CONFIRMED)
    if tenant_id is not None:
        q = q.filter_by(tenant_id=tenant_id)
    count = 0
    for o in q.all():
        try:
            count += len(auto_invoice_stages(o.tenant_id, o.id))
        except (ValueError, LookupError):
            db.session.rollback()
    return count


# ------------------------------------------------------------------ #
#  Full payment -> PAY-CLOSED
# ------------------------------------------------------------------ #

def close_if_settled(tenant_id: int, order_id: int) -> int:
    """Close every milestone once all four stages exist and are fully received."""
    payments = list_for_order(tenant_id, order_id)
    stages = {p.payment_stage for p in payments}
    if not set(PaymentStage.ALL).issubset(stages):
        return 0
    if any(p.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED) for p in payments):
        return 0
    closed = 0
    for p in payments:
        if p.status == PaymentStatus.RECEIVED:
            p.status     = PaymentStatus.CLOSED
            p.updated_at = datetime.utcnow()
            closed += 1
    if closed:
        db.session.commit()
    return closed


# ------------------------------------------------------------------ #
#  Apply / release hold  →  PAY-HOLD_APPLIED
# ------------------------------------------------------------------ #

def apply_hold(tenant_id: int, payment_id: int, hold_reason: str) -> Payment:
    if not hold_reason or not hold_reason.strip():
        raise ValueError('A hold reason is required.')
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.status in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
        raise ValueError(f'Cannot apply hold on a settled payment; status={payment.status}')

    payment.status      = PaymentStatus.HOLD_APPLIED
    payment.hold_flag    = True
    payment.hold_reason  = hold_reason.strip()
    payment.updated_at   = datetime.utcnow()
    db.session.commit()
    return payment


def release_hold(tenant_id: int, payment_id: int) -> Payment:
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.status != PaymentStatus.HOLD_APPLIED:
        raise ValueError(f'Payment is not on hold; status={payment.status}')

    payment.status     = PaymentStatus.PARTIAL if payment.amount_received else PaymentStatus.INVOICED
    payment.hold_flag   = False
    payment.updated_at  = datetime.utcnow()
    db.session.commit()
    return payment


# ------------------------------------------------------------------ #
#  Close payment  →  PAY-CLOSED
# ------------------------------------------------------------------ #

def close_payment(tenant_id: int, payment_id: int) -> Payment:
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.status != PaymentStatus.RECEIVED:
        raise ValueError(f'Payment must be PAY-RECEIVED before closing; status={payment.status}')

    payment.status     = PaymentStatus.CLOSED
    payment.updated_at = datetime.utcnow()
    db.session.commit()
    return payment


# ------------------------------------------------------------------ #
#  Mark overdue  (batch / cron)
# ------------------------------------------------------------------ #

def mark_overdue(tenant_id: int | None = None) -> int:
    today = date.today()
    query = Payment.query.filter(
        Payment.status.in_([PaymentStatus.INVOICED, PaymentStatus.PARTIAL]),
        Payment.due_date.isnot(None),
        Payment.due_date < today,
    )
    if tenant_id is not None:
        query = query.filter(Payment.tenant_id == tenant_id)

    overdue = query.all()
    for p in overdue:
        p.status     = PaymentStatus.OVERDUE
        p.updated_at = datetime.utcnow()
    if overdue:
        db.session.commit()
    return len(overdue)
