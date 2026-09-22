from datetime import datetime, date
from decimal import Decimal

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStatus, PaymentStage


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
) -> Payment:
    order = _require_confirmed_order(tenant_id, order_id)

    if payment_stage not in PaymentStage.ALL:
        raise ValueError(f'Invalid payment stage: {payment_stage}')

    if payment_stage == PaymentStage.ADVANCE and get_advance_for_order(tenant_id, order_id):
        raise ValueError('An advance invoice already exists for this order.')

    if not invoice_amount or Decimal(str(invoice_amount)) <= 0:
        raise ValueError('Invoice amount must be greater than zero.')

    payment = Payment(
        tenant_id      = tenant_id,
        order_id       = order.id,
        payment_number = Payment.generate_number(tenant_id),
        payment_stage  = payment_stage,
        status         = PaymentStatus.INVOICED,
        invoice_amount = Decimal(str(invoice_amount)),
        amount_received= Decimal('0'),
        due_date       = due_date,
        raised_by      = raised_by,
        created_at     = datetime.utcnow(),
        updated_at     = datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()
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
) -> Payment:
    payment = get_payment(tenant_id, payment_id)
    if not payment:
        raise LookupError('Payment not found')
    if payment.status in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
        raise ValueError(f'Payment is already settled; status={payment.status}')
    if not amount_received or Decimal(str(amount_received)) <= 0:
        raise ValueError('Amount received must be greater than zero.')

    now = datetime.utcnow()
    new_total = (payment.amount_received or Decimal('0')) + Decimal(str(amount_received))
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

    # Advance received → release order to Manufacturing (Section 11 boundary)
    if payment.payment_stage == PaymentStage.ADVANCE and payment.status == PaymentStatus.RECEIVED:
        _release_to_manufacturing(payment.order)

    return payment


def _release_to_manufacturing(order: Order) -> None:
    """Hook: advance PAY-RECEIVED unblocks Manufacturing (Section 11)."""
    # Manufacturing module not yet built — placeholder hook for that stage.
    pass


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
