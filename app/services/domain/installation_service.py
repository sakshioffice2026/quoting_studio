from datetime import datetime, date

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStatus, PaymentStage
from ...models.manufacturing_job import ManufacturingJob
from ...models.delivery import Delivery, DeliveryItem, DeliveryStatus
from ...models.installation import (
    Installation, InstallationItem, InstallationStatus, TestResult,
)


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_installation(tenant_id: int, installation_id: int) -> Installation | None:
    return Installation.query.filter_by(id=installation_id, tenant_id=tenant_id).first()


def list_for_order(tenant_id: int, order_id: int) -> list[Installation]:
    from sqlalchemy import asc
    return (Installation.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(Installation.created_at))
            .all())


def list_installations(tenant_id: int, status: str | None = None) -> list[Installation]:
    from sqlalchemy import desc
    q = Installation.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(Installation.created_at)).all()


def delivered_items(tenant_id: int, order_id: int) -> list[DeliveryItem]:
    """Delivery items whose delivery is DEL-DELIVERED (issues resolved)."""
    return (DeliveryItem.query
            .join(Delivery, Delivery.id == DeliveryItem.delivery_id)
            .filter(
                DeliveryItem.tenant_id == tenant_id,
                Delivery.tenant_id == tenant_id,
                Delivery.order_id == order_id,
                Delivery.status == DeliveryStatus.DELIVERED,
            )
            .all())


def installed_opening_ids(tenant_id: int, order_id: int) -> set[int]:
    """Openings already assigned to any installation of this order."""
    rows = (InstallationItem.query
            .join(Installation, Installation.id == InstallationItem.installation_id)
            .filter(
                InstallationItem.tenant_id == tenant_id,
                Installation.tenant_id == tenant_id,
                Installation.order_id == order_id,
            )
            .with_entities(InstallationItem.opening_id)
            .all())
    return {r[0] for r in rows}


def pending_openings(tenant_id: int, order_id: int) -> list[DeliveryItem]:
    """Delivered openings not yet assigned to an installation."""
    taken = installed_opening_ids(tenant_id, order_id)
    return [i for i in delivered_items(tenant_id, order_id) if i.opening_id not in taken]


def orders_ready_for_installation(tenant_id: int) -> list[dict]:
    """Confirmed orders that have delivered openings still waiting to be scheduled."""
    from sqlalchemy import desc
    orders = (Order.query
              .filter_by(tenant_id=tenant_id, status=OrderStatus.CONFIRMED)
              .order_by(desc(Order.created_at))
              .all())
    rows = []
    for order in orders:
        pending = pending_openings(tenant_id, order.id)
        if pending:
            rows.append({'order': order, 'pending': pending})
    return rows


def completed_opening_ids(tenant_id: int, order_id: int) -> set[int]:
    rows = (InstallationItem.query
            .join(Installation, Installation.id == InstallationItem.installation_id)
            .filter(
                InstallationItem.tenant_id == tenant_id,
                Installation.tenant_id == tenant_id,
                Installation.order_id == order_id,
                Installation.status == InstallationStatus.COMPLETED,
            )
            .with_entities(InstallationItem.opening_id)
            .all())
    return {r[0] for r in rows}


def is_order_fully_installed(tenant_id: int, order_id: int) -> bool:
    """INSTALL-COMPLETED for every manufactured opening → project closes, moves to AMC."""
    jobs = ManufacturingJob.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()
    if not jobs:
        return False
    done = completed_opening_ids(tenant_id, order_id)
    return all(j.opening_id in done for j in jobs)


def on_installation_payments(tenant_id: int, order_id: int) -> list[Payment]:
    return (Payment.query
            .filter_by(tenant_id=tenant_id, order_id=order_id,
                       payment_stage=PaymentStage.ON_INSTALLATION)
            .order_by(Payment.created_at)
            .all())


def order_summary(tenant_id: int, order_id: int) -> dict:
    """Order-level installation progress across every installation visit."""
    jobs = ManufacturingJob.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()
    total = len(jobs)

    delivered = {i.opening_id for i in delivered_items(tenant_id, order_id)}
    items = (InstallationItem.query
             .join(Installation, Installation.id == InstallationItem.installation_id)
             .filter(
                 InstallationItem.tenant_id == tenant_id,
                 Installation.tenant_id == tenant_id,
                 Installation.order_id == order_id,
             )
             .all())

    completed = completed_opening_ids(tenant_id, order_id)
    open_snags = sum(1 for i in items if i.has_open_snag)
    scheduled = {i.opening_id for i in items}

    summary = {
        'total':       total,
        'delivered':   len(delivered),
        'scheduled':   len(scheduled),
        'installed':   len(completed),
        'open_snags':  open_snags,
        'unscheduled': len(delivered - scheduled),
    }
    summary['pending'] = total - summary['installed']
    return summary


def flow_snapshot(tenant_id: int, project_id: int | None) -> dict | None:
    """
    Project-level Installation snapshot for the /leads/<id>/flow timeline.
    Returns None when nothing has reached the Installation stage yet.
    """
    if not project_id:
        return None

    orders = Order.query.filter_by(tenant_id=tenant_id, project_id=project_id).all()
    if not orders:
        return None
    order_ids = [o.id for o in orders]

    installations = (Installation.query
                     .filter(Installation.tenant_id == tenant_id,
                             Installation.order_id.in_(order_ids))
                     .order_by(Installation.created_at)
                     .all())

    ready = sum(len(pending_openings(tenant_id, oid)) for oid in order_ids)

    if not installations:
        if not ready:
            return None
        return {
            'installations':     [],
            'status':            None,
            'fully_installed':   False,
            'ready_to_schedule': ready,
            'openings':          0,
            'passed':            0,
            'open_snags':        0,
        }

    statuses = {i.status for i in installations}
    job_order_ids = {
        j.order_id for j in
        ManufacturingJob.query.filter(
            ManufacturingJob.tenant_id == tenant_id,
            ManufacturingJob.order_id.in_(order_ids),
        ).all()
    }
    fully = bool(job_order_ids) and all(
        is_order_fully_installed(tenant_id, oid) for oid in job_order_ids
    )

    if InstallationStatus.SNAG in statuses:
        status = InstallationStatus.SNAG
    elif InstallationStatus.IN_PROGRESS in statuses:
        status = InstallationStatus.IN_PROGRESS
    elif InstallationStatus.SCHEDULED in statuses:
        status = InstallationStatus.SCHEDULED
    else:
        status = InstallationStatus.COMPLETED

    return {
        'installations':     installations,
        'status':            status,
        'fully_installed':   fully,
        'ready_to_schedule': ready,
        'openings':          sum(len(i.items) for i in installations),
        'passed':            sum(i.passed_count for i in installations),
        'open_snags':        sum(i.open_snag_count for i in installations),
    }


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


def _require_no_payment_hold(tenant_id: int, order_id: int) -> None:
    payments = Payment.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()
    for p in payments:
        if p.hold_flag or p.status == PaymentStatus.HOLD_APPLIED:
            raise ValueError(
                f'Installation is blocked: payment {p.payment_number} has a hold applied.'
            )


def _get_or_raise(tenant_id: int, installation_id: int) -> Installation:
    installation = get_installation(tenant_id, installation_id)
    if not installation:
        raise LookupError('Installation not found')
    return installation


def _get_item(installation: Installation, item_id: int) -> InstallationItem:
    item = next((i for i in installation.items if i.id == item_id), None)
    if not item:
        raise LookupError('Installation item not found')
    return item


def _refresh_status(installation: Installation) -> None:
    """IN_PROGRESS ↔ SNAG depending on whether any opening has an open snag."""
    if installation.status not in InstallationStatus.ACTIVE:
        return
    if installation.open_snag_count:
        installation.status = InstallationStatus.SNAG
    else:
        installation.status = InstallationStatus.IN_PROGRESS


# ------------------------------------------------------------------ #
#  Schedule  →  INSTALL-SCHEDULED
# ------------------------------------------------------------------ #

def create_installation(
    tenant_id:          int,
    order_id:           int,
    created_by:         int,
    opening_ids:        list[int] | None = None,
    scheduled_date:     date | None = None,
    team_lead_name:     str | None = None,
    installation_address: str | None = None,
    site_contact_name:  str | None = None,
    site_contact_phone: str | None = None,
) -> Installation:
    order = _require_order(tenant_id, order_id)

    available = pending_openings(tenant_id, order_id)
    if not available:
        raise ValueError('No delivered openings are pending installation for this order.')

    available_map = {i.opening_id: i for i in available}
    if opening_ids:
        invalid = [oid for oid in opening_ids if oid not in available_map]
        if invalid:
            raise ValueError(
                f'Openings not ready for installation (not DEL-DELIVERED or already scheduled): {invalid}'
            )
        selected = [available_map[oid] for oid in opening_ids]
    else:
        selected = available

    # Default site details from the latest delivery on this order
    if not installation_address or not site_contact_name or not site_contact_phone:
        last_delivery = (Delivery.query
                         .filter_by(tenant_id=tenant_id, order_id=order_id)
                         .order_by(Delivery.created_at.desc())
                         .first())
        if last_delivery:
            installation_address = installation_address or last_delivery.delivery_address
            site_contact_name    = site_contact_name    or last_delivery.site_contact_name
            site_contact_phone   = site_contact_phone   or last_delivery.site_contact_phone

    now = datetime.utcnow()
    installation = Installation(
        tenant_id            = tenant_id,
        order_id             = order.id,
        install_number       = Installation.generate_number(tenant_id),
        status               = InstallationStatus.SCHEDULED,
        installation_address = installation_address,
        site_contact_name    = site_contact_name,
        site_contact_phone   = site_contact_phone,
        team_lead_name       = team_lead_name,
        scheduled_date       = scheduled_date,
        assigned_to          = created_by,
        created_by           = created_by,
        created_at           = now,
        updated_at           = now,
    )
    db.session.add(installation)
    db.session.flush()

    for d_item in selected:
        db.session.add(InstallationItem(
            tenant_id              = tenant_id,
            installation_id        = installation.id,
            opening_id             = d_item.opening_id,
            delivery_item_id       = d_item.id,
            functional_test_result = TestResult.PENDING,
            created_at             = now,
            updated_at             = now,
        ))

    db.session.commit()
    return installation


def reschedule_installation(
    tenant_id:       int,
    installation_id: int,
    scheduled_date:  date,
    team_lead_name:  str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status != InstallationStatus.SCHEDULED:
        raise ValueError(
            f'Installation must be INSTALL-SCHEDULED to reschedule; status={installation.status}'
        )
    if not scheduled_date:
        raise ValueError('A valid scheduled date is required.')

    installation.scheduled_date = scheduled_date
    if team_lead_name:
        installation.team_lead_name = team_lead_name
    installation.updated_at = datetime.utcnow()
    db.session.commit()
    return installation


# ------------------------------------------------------------------ #
#  Start  →  INSTALL-IN_PROGRESS
# ------------------------------------------------------------------ #

def start_installation(
    tenant_id:       int,
    installation_id: int,
    team_lead_name:  str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status != InstallationStatus.SCHEDULED:
        raise ValueError(
            f'Installation must be INSTALL-SCHEDULED to start; status={installation.status}'
        )
    if not installation.items:
        raise ValueError('Installation has no items.')

    _require_no_payment_hold(tenant_id, installation.order_id)

    now = datetime.utcnow()
    installation.status     = InstallationStatus.IN_PROGRESS
    installation.started_at = now
    if team_lead_name:
        installation.team_lead_name = team_lead_name
    installation.updated_at = now
    db.session.commit()
    return installation


# ------------------------------------------------------------------ #
#  Record opening  →  IN_PROGRESS / SNAG
# ------------------------------------------------------------------ #

def record_opening(
    tenant_id:         int,
    installation_id:   int,
    item_id:           int,
    installed_by:      str,
    result:            str,
    fitted:            bool = False,
    hardware_adjusted: bool = False,
    joints_sealed:     bool = False,
    site_cleaned:      bool = False,
    snag_list:         str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status not in InstallationStatus.ACTIVE:
        raise ValueError(
            'Installation must be INSTALL-IN_PROGRESS or INSTALL-SNAG to record results; '
            f'status={installation.status}'
        )
    if result not in (TestResult.PASS, TestResult.SNAG):
        raise ValueError('Functional test result must be Pass or Snag.')
    if not installed_by:
        raise ValueError('Installed-by name is required.')

    item = _get_item(installation, item_id)

    if result == TestResult.PASS:
        if not (fitted and hardware_adjusted and joints_sealed and site_cleaned):
            raise ValueError('Every checklist step must be ticked before an opening can pass.')
        snag_list = None
    else:
        if not snag_list:
            raise ValueError('Describe the snag when the functional test result is Snag.')

    now = datetime.utcnow()
    item.installed_by            = installed_by
    item.install_date            = now
    item.fitted                  = bool(fitted)
    item.hardware_adjusted       = bool(hardware_adjusted)
    item.joints_sealed           = bool(joints_sealed)
    item.site_cleaned            = bool(site_cleaned)
    item.functional_test_result  = result
    if result == TestResult.SNAG:
        item.snag_list     = snag_list
        item.snag_resolved = False
    item.updated_at = now

    _refresh_status(installation)
    installation.updated_at = now
    db.session.commit()
    return installation


# ------------------------------------------------------------------ #
#  Resolve snags  →  back to IN_PROGRESS (opening must be re-tested)
# ------------------------------------------------------------------ #

def resolve_snag(
    tenant_id:        int,
    installation_id:  int,
    item_id:          int,
    resolution_notes: str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status != InstallationStatus.SNAG:
        raise ValueError(
            f'Installation must be INSTALL-SNAG to resolve snags; status={installation.status}'
        )

    item = _get_item(installation, item_id)
    if not item.has_open_snag:
        raise ValueError('Item has no open snag.')

    now = datetime.utcnow()
    item.snag_resolved          = True
    item.functional_test_result = TestResult.PENDING   # must be re-tested
    if resolution_notes:
        item.snag_list = f'{item.snag_list or ""}\nResolved: {resolution_notes}'.strip()
    item.updated_at = now

    _refresh_status(installation)
    installation.updated_at = now
    db.session.commit()
    return installation


def resolve_all_snags(
    tenant_id:        int,
    installation_id:  int,
    resolution_notes: str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status != InstallationStatus.SNAG:
        raise ValueError(
            f'Installation must be INSTALL-SNAG to resolve snags; status={installation.status}'
        )

    now = datetime.utcnow()
    for item in installation.items:
        if item.has_open_snag:
            item.snag_resolved          = True
            item.functional_test_result = TestResult.PENDING
            if resolution_notes:
                item.snag_list = f'{item.snag_list or ""}\nResolved: {resolution_notes}'.strip()
            item.updated_at = now

    _refresh_status(installation)
    installation.updated_at = now
    db.session.commit()
    return installation


# ------------------------------------------------------------------ #
#  Customer sign-off / handover  →  INSTALL-COMPLETED
# ------------------------------------------------------------------ #

def sign_off(
    tenant_id:          int,
    installation_id:    int,
    signed_by:          str,
    handover_notes:     str | None = None,
    handover_file_path: str | None = None,
) -> Installation:
    installation = _get_or_raise(tenant_id, installation_id)
    if installation.status != InstallationStatus.IN_PROGRESS:
        raise ValueError(
            f'Installation must be INSTALL-IN_PROGRESS (no open snags) to sign off; '
            f'status={installation.status}'
        )
    if not signed_by:
        raise ValueError('Customer signatory name is required.')
    if not installation.all_passed:
        raise ValueError('Every opening must pass its functional test before customer sign-off.')

    now = datetime.utcnow()
    installation.status              = InstallationStatus.COMPLETED
    installation.signed_by           = signed_by
    installation.customer_signoff_at = now
    installation.completed_at        = now
    installation.handover_notes      = handover_notes
    if handover_file_path:
        installation.handover_file_path = handover_file_path
    installation.updated_at          = now
    db.session.commit()
    return installation
