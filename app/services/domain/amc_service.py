from datetime import datetime, date, timedelta

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.payment import Payment, PaymentStatus
from ...models.installation import Installation, InstallationItem, InstallationStatus
from ...models.amc import (
    Warranty, WarrantyStatus,
    AmcContract, AmcStatus, AmcTier,
    ServiceTicket, TicketStatus, ServiceType, Coverage,
)
from . import installation_service


DEFAULT_WARRANTY_MONTHS = 12


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_warranty(tenant_id: int, warranty_id: int) -> Warranty | None:
    return Warranty.query.filter_by(id=warranty_id, tenant_id=tenant_id).first()


def get_warranty_for_order(tenant_id: int, order_id: int) -> Warranty | None:
    return Warranty.query.filter_by(tenant_id=tenant_id, order_id=order_id).first()


def list_warranties(tenant_id: int) -> list[Warranty]:
    from sqlalchemy import desc
    return (Warranty.query
            .filter_by(tenant_id=tenant_id)
            .order_by(desc(Warranty.created_at))
            .all())


def get_contract(tenant_id: int, contract_id: int) -> AmcContract | None:
    return AmcContract.query.filter_by(id=contract_id, tenant_id=tenant_id).first()


def contracts_for_order(tenant_id: int, order_id: int) -> list[AmcContract]:
    from sqlalchemy import asc
    return (AmcContract.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(AmcContract.created_at))
            .all())


def list_contracts(tenant_id: int, status: str | None = None) -> list[AmcContract]:
    from sqlalchemy import desc
    sweep_expired(tenant_id)
    q = AmcContract.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(AmcContract.created_at)).all()


def get_ticket(tenant_id: int, ticket_id: int) -> ServiceTicket | None:
    return ServiceTicket.query.filter_by(id=ticket_id, tenant_id=tenant_id).first()


def list_tickets(tenant_id: int, status: str | None = None,
                 service_type: str | None = None) -> list[ServiceTicket]:
    from sqlalchemy import desc
    q = ServiceTicket.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    if service_type:
        q = q.filter_by(service_type=service_type)
    return q.order_by(desc(ServiceTicket.opened_at)).all()


def tickets_for_order(tenant_id: int, order_id: int) -> list[ServiceTicket]:
    from sqlalchemy import desc
    return (ServiceTicket.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(desc(ServiceTicket.opened_at))
            .all())


def orders_ready_for_warranty(tenant_id: int) -> list[dict]:
    """Confirmed orders that are fully installed but have no warranty registered yet."""
    from sqlalchemy import desc
    orders = (Order.query
              .filter_by(tenant_id=tenant_id, status=OrderStatus.CONFIRMED)
              .order_by(desc(Order.created_at))
              .all())
    rows = []
    for order in orders:
        if get_warranty_for_order(tenant_id, order.id):
            continue
        if installation_service.is_order_fully_installed(tenant_id, order.id):
            rows.append({
                'order':      order,
                'handover_on': _handover_date(tenant_id, order.id),
            })
    return rows


def installed_openings(tenant_id: int, order_id: int) -> list[InstallationItem]:
    """Openings signed off in a completed installation (can be ticketed)."""
    return (InstallationItem.query
            .join(Installation, Installation.id == InstallationItem.installation_id)
            .filter(
                InstallationItem.tenant_id == tenant_id,
                Installation.tenant_id == tenant_id,
                Installation.order_id == order_id,
                Installation.status == InstallationStatus.COMPLETED,
            )
            .all())


def active_contract_for_order(tenant_id: int, order_id: int) -> AmcContract | None:
    sweep_expired(tenant_id)
    return (AmcContract.query
            .filter_by(tenant_id=tenant_id, order_id=order_id, status=AmcStatus.ACTIVE)
            .order_by(AmcContract.amc_end_date.desc())
            .first())


def is_final_payment_closed(tenant_id: int, order_id: int) -> bool:
    """Gate: every invoiced milestone on the order must be PAY-CLOSED before AMC activation.
    Returns True when no payment milestones have been invoiced yet (nothing to block on)."""
    payments = Payment.query.filter_by(tenant_id=tenant_id, order_id=order_id).all()
    if not payments:
        return True
    return all(p.status == PaymentStatus.CLOSED for p in payments)


def coverage_for(tenant_id: int, order_id: int, on_date: date | None = None) -> str:
    """Warranty window first, then a running AMC, otherwise chargeable."""
    on_date = on_date or date.today()
    warranty = get_warranty_for_order(tenant_id, order_id)
    if warranty and warranty.warranty_start_date <= on_date <= warranty.warranty_end_date:
        return Coverage.WARRANTY
    contract = active_contract_for_order(tenant_id, order_id)
    if (contract and contract.amc_start_date and contract.amc_end_date
            and contract.amc_start_date <= on_date <= contract.amc_end_date):
        return Coverage.AMC
    return Coverage.CHARGEABLE


# ------------------------------------------------------------------ #
#  Internal helpers
# ------------------------------------------------------------------ #

def _require_order(tenant_id: int, order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.CONFIRMED:
        raise ValueError(f'Order must be ORDER-CONFIRMED; status={order.status}')
    return order


def _handover_date(tenant_id: int, order_id: int) -> date | None:
    rows = (Installation.query
            .filter_by(tenant_id=tenant_id, order_id=order_id,
                       status=InstallationStatus.COMPLETED)
            .all())
    stamps = [r.completed_at for r in rows if r.completed_at]
    return max(stamps).date() if stamps else None


def _contract_or_raise(tenant_id: int, contract_id: int) -> AmcContract:
    contract = get_contract(tenant_id, contract_id)
    if not contract:
        raise LookupError('AMC contract not found')
    return contract


def _ticket_or_raise(tenant_id: int, ticket_id: int) -> ServiceTicket:
    ticket = get_ticket(tenant_id, ticket_id)
    if not ticket:
        raise LookupError('Service ticket not found')
    return ticket


def sweep_expired(tenant_id: int) -> int:
    """Flip ACTIVE contracts whose end date has passed to AMC-EXPIRED."""
    changed = 0
    for c in AmcContract.query.filter_by(tenant_id=tenant_id, status=AmcStatus.ACTIVE).all():
        if c.is_lapsed:
            c.status     = AmcStatus.EXPIRED
            c.updated_at = datetime.utcnow()
            changed += 1
    if changed:
        db.session.commit()
    return changed


# ------------------------------------------------------------------ #
#  Warranty  →  WARRANTY-ACTIVE
# ------------------------------------------------------------------ #

def register_warranty(
    tenant_id:       int,
    order_id:        int,
    created_by:      int,
    warranty_months: int | None = None,
    terms:           str | None = None,
    start_date:      date | None = None,
) -> Warranty:
    order = _require_order(tenant_id, order_id)

    if get_warranty_for_order(tenant_id, order_id):
        raise ValueError('A warranty is already registered for this order.')
    if not installation_service.is_order_fully_installed(tenant_id, order_id):
        raise ValueError('Every opening must be INSTALL-COMPLETED before a warranty can be registered.')

    months = warranty_months or DEFAULT_WARRANTY_MONTHS
    if months < 1 or months > 120:
        raise ValueError('Warranty period must be between 1 and 120 months.')

    start = start_date or _handover_date(tenant_id, order_id) or date.today()
    now   = datetime.utcnow()

    warranty = Warranty(
        tenant_id           = tenant_id,
        order_id            = order.id,
        warranty_number     = Warranty.generate_number(tenant_id),
        status              = WarrantyStatus.ACTIVE,
        warranty_months     = months,
        warranty_start_date = start,
        warranty_end_date   = Warranty.end_date_for(start, months),
        terms               = terms,
        created_by          = created_by,
        created_at          = now,
        updated_at          = now,
    )
    db.session.add(warranty)
    db.session.commit()
    return warranty


# ------------------------------------------------------------------ #
#  AMC offer  →  AMC-OFFERED
# ------------------------------------------------------------------ #

def offer_amc(
    tenant_id:       int,
    order_id:        int,
    created_by:      int,
    plan_tier:       str,
    annual_fee,
    visits_per_year: int | None = None,
    notes:           str | None = None,
) -> AmcContract:
    order = _require_order(tenant_id, order_id)

    warranty = get_warranty_for_order(tenant_id, order_id)
    if not warranty:
        raise ValueError('Register the warranty before offering an AMC plan.')
    if plan_tier not in AmcTier.ALL:
        raise ValueError('Plan tier must be Basic, Standard or Premium.')

    sweep_expired(tenant_id)
    open_contract = (AmcContract.query
                     .filter(AmcContract.tenant_id == tenant_id,
                             AmcContract.order_id == order_id,
                             AmcContract.status.in_([AmcStatus.OFFERED, AmcStatus.ACTIVE]))
                     .first())
    if open_contract:
        raise ValueError(
            f'Contract {open_contract.amc_number} is already {open_contract.status}; '
            'renew it once it expires instead of offering a new plan.'
        )

    if annual_fee is None or float(annual_fee) < 0:
        raise ValueError('A valid annual fee is required.')

    now = datetime.utcnow()
    contract = AmcContract(
        tenant_id       = tenant_id,
        order_id        = order.id,
        warranty_id     = warranty.id,
        amc_number      = AmcContract.generate_number(tenant_id),
        status          = AmcStatus.OFFERED,
        plan_tier       = plan_tier,
        visits_per_year = visits_per_year or AmcTier.VISITS[plan_tier],
        annual_fee      = annual_fee,
        offered_at      = now,
        notes           = notes,
        created_by      = created_by,
        created_at      = now,
        updated_at      = now,
    )
    db.session.add(contract)
    db.session.commit()
    return contract


# ------------------------------------------------------------------ #
#  AMC activate  →  AMC-ACTIVE
# ------------------------------------------------------------------ #

def activate_amc(
    tenant_id:          int,
    contract_id:        int,
    signed_by:          str,
    amc_start_date:     date | None = None,
    contract_file_path: str | None = None,
) -> AmcContract:
    contract = _contract_or_raise(tenant_id, contract_id)
    if contract.status != AmcStatus.OFFERED:
        raise ValueError(f'Contract must be AMC-OFFERED to activate; status={contract.status}')
    if not signed_by:
        raise ValueError('Customer signatory name is required.')
    if not is_final_payment_closed(tenant_id, contract.order_id):
        raise ValueError('Final payment must be PAY-CLOSED on every milestone before AMC activation.')

    today = date.today()
    start = amc_start_date
    if not start:
        # Renewal continues straight after the previous term; otherwise start after
        # the free warranty ends (or today if the warranty is already over).
        prev_end = contract.renewal_of.amc_end_date if contract.renewal_of else None
        warranty = contract.warranty
        if prev_end and prev_end >= today:
            start = prev_end + timedelta(days=1)
        elif warranty and warranty.warranty_end_date >= today:
            start = warranty.warranty_end_date + timedelta(days=1)
        else:
            start = today

    now = datetime.utcnow()
    contract.status         = AmcStatus.ACTIVE
    contract.amc_start_date = start
    contract.amc_end_date   = Warranty.end_date_for(start, 12) - timedelta(days=1)
    contract.activated_at   = now
    contract.signed_by      = signed_by
    if contract_file_path:
        contract.contract_file_path = contract_file_path
    contract.updated_at     = now
    db.session.commit()
    return contract


# ------------------------------------------------------------------ #
#  AMC renewal  →  new AMC-OFFERED row
# ------------------------------------------------------------------ #

def renew_amc(
    tenant_id:   int,
    contract_id: int,
    created_by:  int,
    plan_tier:   str | None = None,
    annual_fee=None,
    notes:       str | None = None,
) -> AmcContract:
    source = _contract_or_raise(tenant_id, contract_id)
    sweep_expired(tenant_id)
    if source.status not in (AmcStatus.ACTIVE, AmcStatus.EXPIRED):
        raise ValueError(f'Only AMC-ACTIVE or AMC-EXPIRED contracts can be renewed; status={source.status}')

    pending = (AmcContract.query
               .filter_by(tenant_id=tenant_id, renewal_of_id=source.id, status=AmcStatus.OFFERED)
               .first())
    if pending:
        raise ValueError(f'Renewal {pending.amc_number} is already offered for this contract.')

    tier = plan_tier or source.plan_tier
    if tier not in AmcTier.ALL:
        raise ValueError('Plan tier must be Basic, Standard or Premium.')
    fee = annual_fee if annual_fee is not None else source.annual_fee

    now = datetime.utcnow()
    renewal = AmcContract(
        tenant_id       = tenant_id,
        order_id        = source.order_id,
        warranty_id     = source.warranty_id,
        renewal_of_id   = source.id,
        amc_number      = AmcContract.generate_number(tenant_id),
        status          = AmcStatus.OFFERED,
        plan_tier       = tier,
        visits_per_year = AmcTier.VISITS[tier],
        annual_fee      = fee,
        offered_at      = now,
        notes           = notes,
        created_by      = created_by,
        created_at      = now,
        updated_at      = now,
    )
    db.session.add(renewal)
    db.session.commit()
    return renewal


def expiring_contracts(tenant_id: int, within_days: int = 60) -> list[AmcContract]:
    """ACTIVE contracts ending soon — drives renewal reminders."""
    sweep_expired(tenant_id)
    limit = date.today() + timedelta(days=within_days)
    return (AmcContract.query
            .filter(AmcContract.tenant_id == tenant_id,
                    AmcContract.status == AmcStatus.ACTIVE,
                    AmcContract.amc_end_date <= limit)
            .order_by(AmcContract.amc_end_date)
            .all())


# ------------------------------------------------------------------ #
#  Service tickets
# ------------------------------------------------------------------ #

def open_ticket(
    tenant_id:       int,
    order_id:        int,
    created_by:      int,
    service_type:    str,
    title:           str,
    description:     str | None = None,
    opening_id:      int | None = None,
    reported_by:     str | None = None,
    scheduled_date:  date | None = None,
    technician_name: str | None = None,
) -> ServiceTicket:
    order = _require_order(tenant_id, order_id)

    if service_type not in ServiceType.ALL:
        raise ValueError('Service type must be Preventive or Complaint.')
    if not title or not title.strip():
        raise ValueError('A short title is required.')
    if not get_warranty_for_order(tenant_id, order_id):
        raise ValueError('Tickets can only be raised after the warranty is registered (handover complete).')

    if opening_id is not None:
        valid_ids = {i.opening_id for i in installed_openings(tenant_id, order_id)}
        if opening_id not in valid_ids:
            raise ValueError('Selected opening does not belong to this order\'s completed installation.')

    coverage = coverage_for(tenant_id, order_id)
    if service_type == ServiceType.PREVENTIVE and coverage != Coverage.AMC:
        # Preventive visits are an AMC benefit; during warranty use a complaint ticket.
        contract = active_contract_for_order(tenant_id, order_id)
        if not contract:
            raise ValueError('Preventive visits require an active AMC contract.')
        coverage = Coverage.AMC

    contract = active_contract_for_order(tenant_id, order_id) if coverage == Coverage.AMC else None

    now = datetime.utcnow()
    ticket = ServiceTicket(
        tenant_id       = tenant_id,
        order_id        = order.id,
        opening_id      = opening_id,
        amc_contract_id = contract.id if contract else None,
        ticket_number   = ServiceTicket.generate_number(tenant_id),
        service_type    = service_type,
        status          = TicketStatus.OPEN,
        coverage        = coverage,
        title           = title.strip(),
        description     = description,
        reported_by     = reported_by,
        scheduled_date  = scheduled_date,
        technician_name = technician_name,
        opened_at       = now,
        created_by      = created_by,
        created_at      = now,
        updated_at      = now,
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def schedule_ticket(
    tenant_id:       int,
    ticket_id:       int,
    scheduled_date:  date,
    technician_name: str | None = None,
) -> ServiceTicket:
    ticket = _ticket_or_raise(tenant_id, ticket_id)
    if ticket.status not in TicketStatus.ACTIVE:
        raise ValueError(f'Only open tickets can be scheduled; status={ticket.status}')
    if not scheduled_date:
        raise ValueError('A valid scheduled date is required.')

    ticket.scheduled_date = scheduled_date
    if technician_name:
        ticket.technician_name = technician_name
    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    return ticket


def start_ticket(
    tenant_id:       int,
    ticket_id:       int,
    technician_name: str | None = None,
) -> ServiceTicket:
    ticket = _ticket_or_raise(tenant_id, ticket_id)
    if ticket.status != TicketStatus.OPEN:
        raise ValueError(f'Ticket must be TICKET-OPEN to start; status={ticket.status}')

    now = datetime.utcnow()
    ticket.status     = TicketStatus.IN_PROGRESS
    ticket.started_at = now
    if technician_name:
        ticket.technician_name = technician_name
    ticket.updated_at = now
    db.session.commit()
    return ticket


def resolve_ticket(
    tenant_id:        int,
    ticket_id:        int,
    resolution_notes: str,
    resolved_by:      str,
) -> ServiceTicket:
    ticket = _ticket_or_raise(tenant_id, ticket_id)
    if ticket.status != TicketStatus.IN_PROGRESS:
        raise ValueError(f'Ticket must be TICKET-IN_PROGRESS to resolve; status={ticket.status}')
    if not resolution_notes or not resolution_notes.strip():
        raise ValueError('Resolution notes (service visit report) are required.')
    if not resolved_by:
        raise ValueError('Resolved-by name is required.')

    now = datetime.utcnow()
    ticket.status           = TicketStatus.RESOLVED
    ticket.resolution_notes = resolution_notes.strip()
    ticket.resolved_by      = resolved_by
    ticket.resolved_at      = now
    ticket.updated_at       = now
    db.session.commit()
    return ticket


# ------------------------------------------------------------------ #
#  Summaries
# ------------------------------------------------------------------ #

def order_summary(tenant_id: int, order_id: int) -> dict:
    tickets  = tickets_for_order(tenant_id, order_id)
    contract = active_contract_for_order(tenant_id, order_id)
    return {
        'warranty':       get_warranty_for_order(tenant_id, order_id),
        'active_contract': contract,
        'coverage':       coverage_for(tenant_id, order_id),
        'tickets_total':  len(tickets),
        'tickets_open':   sum(1 for t in tickets if t.is_active),
        'final_payment_closed': is_final_payment_closed(tenant_id, order_id),
    }


def flow_snapshot(tenant_id: int, project_id: int | None) -> dict | None:
    """Project-level AMC snapshot for the /leads/<id>/flow timeline."""
    if not project_id:
        return None

    orders = Order.query.filter_by(tenant_id=tenant_id, project_id=project_id).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return None

    sweep_expired(tenant_id)

    warranties = (Warranty.query
                  .filter(Warranty.tenant_id == tenant_id, Warranty.order_id.in_(order_ids))
                  .order_by(Warranty.created_at)
                  .all())
    if not warranties:
        return None

    contracts = (AmcContract.query
                 .filter(AmcContract.tenant_id == tenant_id, AmcContract.order_id.in_(order_ids))
                 .order_by(AmcContract.created_at)
                 .all())
    tickets = (ServiceTicket.query
               .filter(ServiceTicket.tenant_id == tenant_id, ServiceTicket.order_id.in_(order_ids))
               .all())

    statuses = {c.status for c in contracts}
    if AmcStatus.ACTIVE in statuses:
        status = AmcStatus.ACTIVE
    elif AmcStatus.OFFERED in statuses:
        status = AmcStatus.OFFERED
    elif AmcStatus.EXPIRED in statuses:
        status = AmcStatus.EXPIRED
    else:
        status = WarrantyStatus.ACTIVE

    running = [c for c in contracts if c.status == AmcStatus.ACTIVE]
    current = running[-1] if running else (contracts[-1] if contracts else None)

    return {
        'status':          status,
        'warranties':      warranties,
        'contracts':       contracts,
        'current':         current,
        'tickets_total':   len(tickets),
        'tickets_open':    sum(1 for t in tickets if t.is_active),
        'tickets_resolved': sum(1 for t in tickets if t.status == TicketStatus.RESOLVED),
    }
