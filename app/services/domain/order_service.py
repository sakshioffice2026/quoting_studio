from datetime import datetime, date

from ...extensions import db
from ...models import Project, Quotation
from ...models.quotation import QuotationStatus
from ...models.order import Order, OrderStatus


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_order(tenant_id: int, order_id: int) -> Order | None:
    return Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()


def get_for_quotation(tenant_id: int, quotation_id: int) -> Order | None:
    """Return the active (non-cancelled) order raised from this quotation."""
    return (Order.query
            .filter(Order.tenant_id == tenant_id,
                    Order.quotation_id == quotation_id,
                    Order.status != OrderStatus.CANCELLED)
            .first())


def list_for_project(tenant_id: int, project_id: int) -> list[Order]:
    from sqlalchemy import desc
    return (Order.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(desc(Order.created_at))
            .all())


def list_orders(tenant_id: int, status: str | None = None) -> list[Order]:
    from sqlalchemy import desc
    q = Order.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(Order.created_at)).all()


# ------------------------------------------------------------------ #
#  Guard: quotation must be ACCEPTED before an order can be raised
# ------------------------------------------------------------------ #

def _require_accepted_quotation(tenant_id: int, quotation_id: int) -> Quotation:
    q = Quotation.query.filter_by(id=quotation_id, tenant_id=tenant_id).first()
    if not q:
        raise LookupError('Quotation not found')
    if q.status != QuotationStatus.ACCEPTED:
        raise ValueError(
            f'Quotation must be QUOTE-ACCEPTED before raising an order; status={q.status}'
        )
    return q


# ------------------------------------------------------------------ #
#  Create order  →  ORDER-PENDING_SIGNATURE
# ------------------------------------------------------------------ #

def create_order(
    tenant_id:              int,
    quotation_id:           int,
    created_by:             int,
    contract_ref:           str | None = None,
    promised_delivery_date: date | None = None,
) -> Order:
    quotation = _require_accepted_quotation(tenant_id, quotation_id)

    existing = get_for_quotation(tenant_id, quotation_id)
    if existing:
        raise ValueError(f'An order already exists for this quotation: {existing.order_number}')

    project = Project.query.filter_by(id=quotation.project_id, tenant_id=tenant_id).first()
    if not project:
        raise LookupError('Project not found')

    order = Order(
        tenant_id              = tenant_id,
        project_id             = quotation.project_id,
        quotation_id           = quotation.id,
        order_number           = Order.generate_number(tenant_id),
        contract_ref           = contract_ref,
        status                 = OrderStatus.PENDING_SIGNATURE,
        promised_delivery_date = promised_delivery_date,
        total_amount           = quotation.grand_total,
        created_by             = created_by,
        created_at             = datetime.utcnow(),
        updated_at             = datetime.utcnow(),
    )
    db.session.add(order)
    db.session.commit()
    return order


# ------------------------------------------------------------------ #
#  Confirm order  →  ORDER-CONFIRMED
# ------------------------------------------------------------------ #

def confirm_order(
    tenant_id:                int,
    order_id:                 int,
    order_confirmed_by_name:  str,
    confirmation_method:      str = 'email',
    assigned_project_manager: int | None = None,
) -> Order:
    if not order_confirmed_by_name or not order_confirmed_by_name.strip():
        raise ValueError('Customer confirmation name is required.')

    order = get_order(tenant_id, order_id)
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.PENDING_SIGNATURE:
        raise ValueError(
            f'Order must be ORDER-PENDING_SIGNATURE to confirm; status={order.status}'
        )

    now = datetime.utcnow()
    order.status                    = OrderStatus.CONFIRMED
    order.order_confirmed_by_name   = order_confirmed_by_name.strip()
    order.order_confirmed_at        = now
    order.confirmation_method       = confirmation_method
    if assigned_project_manager is not None:
        order.assigned_project_manager = assigned_project_manager
    order.updated_at                = now
    db.session.commit()
    return order


# ------------------------------------------------------------------ #
#  Cancel order  →  ORDER-CANCELLED
# ------------------------------------------------------------------ #

def cancel_order(tenant_id: int, order_id: int, cancelled_reason: str) -> Order:
    if not cancelled_reason or not cancelled_reason.strip():
        raise ValueError('A cancellation reason is required.')

    order = get_order(tenant_id, order_id)
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.PENDING_SIGNATURE:
        raise ValueError(
            f'Only an ORDER-PENDING_SIGNATURE order can be cancelled; status={order.status}'
        )

    now = datetime.utcnow()
    order.status           = OrderStatus.CANCELLED
    order.cancelled_reason = cancelled_reason.strip()
    order.cancelled_at     = now
    order.updated_at       = now
    db.session.commit()
    return order
