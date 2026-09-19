from ...models import Order, Quotation
from ...models.order import OrderStatus
from ...models.quotation import QuotationStatus


def get_lock_reason(tenant_id: int, project_id: int) -> str | None:
    """
    Return a human-readable reason if the project's design/units must not be
    changed any more, otherwise None.

    A project is locked once it has a non-cancelled Order, or an ACCEPTED
    Quotation.
    """
    order = (Order.query
             .filter(Order.tenant_id == tenant_id,
                     Order.project_id == project_id,
                     Order.status != OrderStatus.CANCELLED)
             .first())
    if order:
        return (f'Order {order.order_number} exists for this project — '
                f'units and designs are locked.')

    accepted = (Quotation.query
                .filter_by(tenant_id=tenant_id,
                           project_id=project_id,
                           status=QuotationStatus.ACCEPTED)
                .first())
    if accepted:
        return (f'Quotation {accepted.quotation_number} has been accepted — '
                f'units and designs are locked.')

    return None


def is_locked(tenant_id: int, project_id: int) -> bool:
    return get_lock_reason(tenant_id, project_id) is not None
