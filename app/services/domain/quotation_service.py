import json
from datetime import datetime, date, timedelta
from decimal import Decimal

from ...extensions import db
from ...models import Project, Window, DesignApproval
from ...models.design_approval import DesignApprovalStatus
from ...models.quotation import Quotation, QuotationStatus
from ..domain.pricing import calculate_price

# Default validity period (days) — tenant-configurable later
DEFAULT_VALIDITY_DAYS = 30

# Discount threshold above which manager approval is required (%)
DISCOUNT_APPROVAL_THRESHOLD = Decimal('10.00')


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_quotation(tenant_id: int, quotation_id: int) -> Quotation | None:
    return Quotation.query.filter_by(
        id=quotation_id, tenant_id=tenant_id
    ).first()


def get_latest_for_project(tenant_id: int, project_id: int) -> Quotation | None:
    from sqlalchemy import desc
    return (Quotation.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(desc(Quotation.created_at))
            .first())


def list_for_project(tenant_id: int, project_id: int) -> list[Quotation]:
    from sqlalchemy import desc
    return (Quotation.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(desc(Quotation.quotation_version))
            .all())


def list_quotations(tenant_id: int, status: str | None = None) -> list[Quotation]:
    from sqlalchemy import desc
    q = Quotation.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(Quotation.created_at)).all()


def is_project_quoted(tenant_id: int, project_id: int) -> bool:
    latest = get_latest_for_project(tenant_id, project_id)
    return bool(latest and latest.status in (
        QuotationStatus.SENT, QuotationStatus.NEGOTIATION, QuotationStatus.ACCEPTED
    ))


# ------------------------------------------------------------------ #
#  Guard: design must be APPROVED before quoting
# ------------------------------------------------------------------ #

def _require_approved_design(tenant_id: int, project_id: int) -> DesignApproval:
    from sqlalchemy import desc
    approval = (DesignApproval.query
                .filter_by(tenant_id=tenant_id, project_id=project_id,
                            status=DesignApprovalStatus.APPROVED)
                .order_by(desc(DesignApproval.revision_number))
                .first())
    if not approval:
        raise ValueError(
            'A customer-approved design (APPROVAL-APPROVED) is required before generating a quotation.'
        )
    return approval


# ------------------------------------------------------------------ #
#  Build line items from project windows
# ------------------------------------------------------------------ #

def _build_line_items(windows, tenant_id: int) -> tuple[list[dict], Decimal]:
    """Return (line_items, subtotal)."""
    items    = []
    subtotal = Decimal('0')

    for w in windows:
        panes  = w.panes.all()
        design = None
        try:
            if getattr(w, 'design_json', None):
                design = json.loads(w.design_json)
        except (ValueError, TypeError):
            pass

        price = calculate_price(w, panes, tenant_id, design=design)
        total = Decimal(str(price['total']))
        subtotal += total

        items.append({
            'opening_id':   getattr(w, 'survey_opening_id', None),
            'window_id':    w.id,
            'label':        getattr(w, 'label', f'Window {w.id}'),
            'material':     w.material,
            'width_mm':     w.width_mm,
            'height_mm':    w.height_mm,
            'frame':        price['frame'],
            'hardware':     price['hardware'],
            'extras':       price['extras'],
            'fitting':      price['fitting'],
            'unit_total':   price['total'],
            'qty':          1,
            'amount':       price['total'],
        })

    return items, subtotal


# ------------------------------------------------------------------ #
#  Create quotation
# ------------------------------------------------------------------ #

def create_quotation(
    tenant_id:              int,
    project_id:             int,
    prepared_by:            int,
    discount_pct:           float   = 0.0,
    tax_rate:               float   = 0.20,
    validity_days:          int     = DEFAULT_VALIDITY_DAYS,
    payment_terms_template: str     | None = None,
) -> Quotation:
    project  = Project.query.filter_by(id=project_id, tenant_id=tenant_id).first()
    if not project:
        raise LookupError('Project not found')

    approval = _require_approved_design(tenant_id, project_id)

    windows = project.windows.all()
    if not windows:
        raise ValueError('Project has no windows/openings to quote.')

    # Versioning
    prior        = get_latest_for_project(tenant_id, project_id)
    new_version  = (prior.quotation_version + 1) if prior else 1
    parent_id    = prior.id if prior else None

    # Supersede any active prior quotation
    if prior and prior.status not in QuotationStatus.TERMINAL:
        prior.status = QuotationStatus.EXPIRED
        db.session.add(prior)

    line_items, subtotal = _build_line_items(windows, tenant_id)

    disc_pct    = Decimal(str(discount_pct))
    disc_amount = (subtotal * disc_pct / 100).quantize(Decimal('0.01'))
    taxable     = subtotal - disc_amount
    tax_amt     = (taxable * Decimal(str(tax_rate))).quantize(Decimal('0.01'))
    grand_total = (taxable + tax_amt).quantize(Decimal('0.01'))

    # Discount approval gate
    needs_discount_approval = disc_pct > DISCOUNT_APPROVAL_THRESHOLD
    initial_status = (
        QuotationStatus.PENDING_DISCOUNT_APPROVAL
        if needs_discount_approval
        else QuotationStatus.DRAFT
    )

    quotation = Quotation(
        tenant_id               = tenant_id,
        project_id              = project_id,
        design_approval_id      = approval.id,
        quotation_number        = Quotation.generate_number(tenant_id),
        quotation_version       = new_version,
        parent_quotation_id     = parent_id,
        status                  = initial_status,
        line_items_json         = json.dumps(line_items),
        subtotal                = subtotal,
        discount_pct            = disc_pct,
        discount_amount         = disc_amount,
        tax_rate                = Decimal(str(tax_rate)),
        tax_amount              = tax_amt,
        grand_total             = grand_total,
        payment_terms_template  = payment_terms_template,
        validity_days           = validity_days,
        validity_date           = date.today() + timedelta(days=validity_days),
        prepared_by             = prepared_by,
        created_at              = datetime.utcnow(),
        updated_at              = datetime.utcnow(),
    )
    db.session.add(quotation)
    db.session.commit()
    return quotation


# ------------------------------------------------------------------ #
#  Discount approval
# ------------------------------------------------------------------ #

def approve_discount(tenant_id: int, quotation_id: int, approved_by: int) -> Quotation:
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    if q.status != QuotationStatus.PENDING_DISCOUNT_APPROVAL:
        raise ValueError(f'Quotation is not awaiting discount approval; status={q.status}')
    q.status               = QuotationStatus.DRAFT
    q.discount_approved_by = approved_by
    q.discount_approved_at = datetime.utcnow()
    q.updated_at           = datetime.utcnow()
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Send to customer  →  QUOTE-SENT
# ------------------------------------------------------------------ #

def send_to_customer(tenant_id: int, quotation_id: int, sent_by: int) -> Quotation:
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    if q.status != QuotationStatus.DRAFT:
        raise ValueError(
            f'Only a QUOTE-DRAFT quotation can be sent to the customer; status={q.status}'
        )
    now = datetime.utcnow()
    q.status      = QuotationStatus.SENT
    q.sent_by     = sent_by
    q.sent_at     = now
    q.updated_at  = now
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Enter negotiation  →  QUOTE-NEGOTIATION
# ------------------------------------------------------------------ #

def mark_negotiation(tenant_id: int, quotation_id: int, notes: str | None = None) -> Quotation:
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    if q.status != QuotationStatus.SENT:
        raise ValueError(f'Quotation must be QUOTE-SENT to enter negotiation; status={q.status}')
    q.status             = QuotationStatus.NEGOTIATION
    q.negotiation_notes  = notes
    q.updated_at         = datetime.utcnow()
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Accept  →  QUOTE-ACCEPTED
# ------------------------------------------------------------------ #

def accept_quotation(
    tenant_id:         int,
    quotation_id:      int,
    accepted_by_name:  str,
    acceptance_method: str  = 'email',
) -> Quotation:
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    _acceptable = (QuotationStatus.SENT, QuotationStatus.NEGOTIATION)
    if q.status not in _acceptable:
        raise ValueError(
            f'Quotation must be QUOTE-SENT or QUOTE-NEGOTIATION to accept; status={q.status}'
        )
    now = datetime.utcnow()
    q.status            = QuotationStatus.ACCEPTED
    q.accepted_by_name  = accepted_by_name
    q.accepted_at       = now
    q.acceptance_method = acceptance_method
    q.updated_at        = now
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Mark lost  →  QUOTE-LOST
# ------------------------------------------------------------------ #

def mark_lost(tenant_id: int, quotation_id: int, lost_reason: str) -> Quotation:
    if not lost_reason or not lost_reason.strip():
        raise ValueError('A lost reason is required.')
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    _losable = (QuotationStatus.SENT, QuotationStatus.NEGOTIATION, QuotationStatus.DRAFT)
    if q.status not in _losable:
        raise ValueError(f'Cannot mark quotation as lost from status={q.status}')
    now = datetime.utcnow()
    q.status      = QuotationStatus.LOST
    q.lost_reason = lost_reason.strip()
    q.lost_at     = now
    q.updated_at  = now
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Expire overdue quotations  (batch / cron)
# ------------------------------------------------------------------ #

def expire_overdue(tenant_id: int | None = None) -> int:
    today = date.today()
    query = Quotation.query.filter(
        Quotation.status == QuotationStatus.SENT,
        Quotation.validity_date.isnot(None),
        Quotation.validity_date < today,
    )
    if tenant_id is not None:
        query = query.filter(Quotation.tenant_id == tenant_id)

    overdue = query.all()
    for q in overdue:
        q.status     = QuotationStatus.EXPIRED
        q.updated_at = datetime.utcnow()
    if overdue:
        db.session.commit()
    return len(overdue)
