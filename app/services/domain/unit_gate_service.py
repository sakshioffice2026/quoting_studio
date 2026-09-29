from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStage, PaymentStatus
from ...models.order_unit_release import OrderUnitRelease, UnitReleaseStatus
from ...models.window import Window

_SETTLED = (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)


# ------------------------------------------------------------------ #
#  Lookups (always read live from the DB)
# ------------------------------------------------------------------ #

def stage_payment(tenant_id: int, order_id: int, stage: str) -> Payment | None:
    return (Payment.query
            .filter_by(tenant_id=tenant_id, order_id=order_id, payment_stage=stage)
            .order_by(Payment.id.asc())
            .first())


def _unit_rows(tenant_id: int, payment_id: int) -> list[OrderUnitRelease]:
    return (OrderUnitRelease.query
            .filter_by(tenant_id=tenant_id, payment_id=payment_id)
            .all())


def _order_on_hold(tenant_id: int, order_id: int) -> Payment | None:
    return (Payment.query
            .filter(Payment.tenant_id == tenant_id,
                    Payment.order_id == order_id,
                    db.or_(Payment.hold_flag.is_(True),
                           Payment.status == PaymentStatus.HOLD_APPLIED))
            .first())


# ------------------------------------------------------------------ #
#  Core check
# ------------------------------------------------------------------ #

def unit_lock_reason(tenant_id: int, order_id: int, window_id: int,
                     stage: str = PaymentStage.ADVANCE) -> str | None:
    """None -> unit is unlocked for `stage`. Otherwise the reason it is locked."""
    held = _order_on_hold(tenant_id, order_id)
    if held:
        return f'payment {held.payment_number} has a hold applied'

    payment = stage_payment(tenant_id, order_id, stage)
    if payment is None:
        if stage == PaymentStage.ADVANCE:
            return 'advance invoice has not been raised'
        return None  # later stage not invoiced yet -> no gate

    if payment.is_unit_wise:
        row = next((r for r in _unit_rows(tenant_id, payment.id)
                    if r.window_id == window_id), None)
        if row is None:
            return f'unit is not on the {stage} ledger'
        if row.status != UnitReleaseStatus.RELEASED:
            return (f'{stage} payment for this unit is not fully covered '
                    f'(short by {row.shortfall})')
        return None

    if payment.status not in _SETTLED:
        return f'{stage} payment {payment.payment_number} is not received'
    return None


def is_unit_released(tenant_id: int, order_id: int, window_id: int,
                     stage: str = PaymentStage.ADVANCE) -> bool:
    return unit_lock_reason(tenant_id, order_id, window_id, stage) is None


def require_unit_released(tenant_id: int, order_id: int, window_id: int,
                          stage: str = PaymentStage.ADVANCE, action: str = 'proceed') -> None:
    reason = unit_lock_reason(tenant_id, order_id, window_id, stage)
    if reason:
        raise ValueError(f'Cannot {action}: unit {window_id} is locked - {reason}.')


def require_openings_released(tenant_id: int, order_id: int, window_ids,
                              stage: str = PaymentStage.ADVANCE, action: str = 'proceed') -> None:
    locked = []
    for wid in window_ids:
        reason = unit_lock_reason(tenant_id, order_id, wid, stage)
        if reason:
            locked.append(f'unit {wid} ({reason})')
    if locked:
        raise ValueError(f'Cannot {action}: ' + '; '.join(locked) + '.')


# ------------------------------------------------------------------ #
#  Bulk helpers
# ------------------------------------------------------------------ #

def released_window_ids(tenant_id: int, order_id: int,
                        stage: str = PaymentStage.ADVANCE) -> list[int] | None:
    """
    None -> whole-order mode (no per-unit filter; use payment status).
    list -> unit-wise mode; only these window ids are unlocked.
    """
    payment = stage_payment(tenant_id, order_id, stage)
    if payment is None or not payment.is_unit_wise:
        return None
    if _order_on_hold(tenant_id, order_id):
        return []
    return [r.window_id for r in _unit_rows(tenant_id, payment.id)
            if r.status == UnitReleaseStatus.RELEASED and r.window_id]


def filter_released(tenant_id: int, order_id: int, window_ids,
                    stage: str = PaymentStage.ADVANCE) -> list[int]:
    return [w for w in window_ids if is_unit_released(tenant_id, order_id, w, stage)]


def any_unit_released(tenant_id: int, order_id: int,
                      stage: str = PaymentStage.ADVANCE) -> bool:
    payment = stage_payment(tenant_id, order_id, stage)
    if payment is None or _order_on_hold(tenant_id, order_id):
        return False
    if payment.is_unit_wise:
        return any(r.status == UnitReleaseStatus.RELEASED
                   for r in _unit_rows(tenant_id, payment.id))
    return payment.status in _SETTLED


# ------------------------------------------------------------------ #
#  Design lock (post-order revisions)
# ------------------------------------------------------------------ #

def design_locked_window_ids(tenant_id: int, project_id: int) -> set[int]:
    order = (Order.query
             .filter_by(tenant_id=tenant_id, project_id=project_id,
                        status=OrderStatus.CONFIRMED)
             .order_by(Order.id.desc())
             .first())
    if order is None:
        return set()
    advance = stage_payment(tenant_id, order.id, PaymentStage.ADVANCE)
    if advance is None or not advance.is_unit_wise:
        return set()
    released = set(released_window_ids(tenant_id, order.id, PaymentStage.ADVANCE) or [])
    all_ids = {w.id for w in Window.query.filter_by(tenant_id=tenant_id,
                                                    project_id=project_id).all()}
    return all_ids - released
