import json
from datetime import datetime, date, timedelta
from decimal import Decimal

from sqlalchemy import or_, desc

from ...extensions import db
from ...models.amc import AmcTier
from ...models import Project, Window, DesignApproval
from ...models.design_approval import DesignApprovalStatus
from ...models.quotation import Quotation, QuotationStatus
from ..domain.pricing import calculate_price


def _tenant_currency(tenant_id):
    from ...models.tenant import Tenant
    tenant = db.session.get(Tenant, tenant_id) if tenant_id else None
    return (tenant.currency_code if tenant and tenant.currency_code else "INR")

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


def _get_approved_design(tenant_id: int, project_id: int) -> DesignApproval | None:
    """Latest customer-approved design for the project, or None (never raises)."""
    return (DesignApproval.query
            .filter_by(tenant_id=tenant_id, project_id=project_id,
                       status=DesignApprovalStatus.APPROVED)
            .order_by(desc(DesignApproval.revision_number))
            .first())


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
#  Create indicative quotation from Preliminary Selection (no design required)
# ------------------------------------------------------------------ #

def create_indicative_quotation(
    tenant_id:    int,
    project_id:   int,
    presel,
    prepared_by:  int,
    validity_days: int = DEFAULT_VALIDITY_DAYS,
) -> 'Quotation':
    """Creates a QUOTE-DRAFT directly from a PreliminarySelection record,
    bypassing the design-approval gate. Line items are budget-band stubs
    derived from rough opening counts and the indicative price range."""
    project = Project.query.filter_by(id=project_id, tenant_id=tenant_id).first()
    if not project:
        raise LookupError('Project not found')

    prior       = get_latest_for_project(tenant_id, project_id)
    new_version = (prior.quotation_version + 1) if prior else 1
    parent_id   = prior.id if prior else None

    if prior and prior.status not in QuotationStatus.TERMINAL:
        prior.status = QuotationStatus.EXPIRED
        db.session.add(prior)

    # Build stub line items from rough opening counts
    line_items = []
    subtotal   = Decimal('0')

    price_min = Decimal(str(presel.indicative_price_min or 0))
    price_max = Decimal(str(presel.indicative_price_max or 0))
    mid_price = ((price_min + price_max) / 2) if (price_min or price_max) else Decimal('0')

    doors   = presel.rough_opening_doors   or 0
    windows = presel.rough_opening_windows or 0
    total_openings = doors + windows

    def _unit_rate(count):
        if not count or not mid_price:
            return Decimal('0')
        return (mid_price / total_openings).quantize(Decimal('0.01'))

    unit_rate = _unit_rate(total_openings)

    if windows:
        amt = (unit_rate * windows).quantize(Decimal('0.01'))
        line_items.append({
            'label':      'Windows (indicative)',
            'note':       presel.shortlisted_ranges or '',
            'qty':        windows,
            'unit':       'opening',
            'unit_total': float(unit_rate),
            'amount':     float(amt),
            'indicative': True,
        })
        subtotal += amt

    if doors:
        amt = (unit_rate * doors).quantize(Decimal('0.01'))
        line_items.append({
            'label':      'Doors (indicative)',
            'note':       presel.shortlisted_ranges or '',
            'qty':        doors,
            'unit':       'opening',
            'unit_total': float(unit_rate),
            'amount':     float(amt),
            'indicative': True,
        })
        subtotal += amt

    if not line_items:
        line_items.append({
            'label':      'Indicative scope (TBD)',
            'note':       presel.shortlisted_ranges or '',
            'qty':        1,
            'unit':       'lot',
            'unit_total': float(mid_price),
            'amount':     float(mid_price),
            'indicative': True,
        })
        subtotal = mid_price

    import json
    quotation = Quotation(
        tenant_id              = tenant_id,
        currency_code          = _tenant_currency(tenant_id),
        project_id             = project_id,
        design_approval_id     = None,
        quotation_number       = Quotation.generate_number(tenant_id),
        quotation_version      = new_version,
        parent_quotation_id    = parent_id,
        status                 = QuotationStatus.DRAFT,
        line_items_json        = json.dumps(line_items),
        subtotal               = subtotal,
        discount_pct           = Decimal('0'),
        discount_amount        = Decimal('0'),
        tax_rate               = Decimal('0.00'),
        tax_amount             = Decimal('0'),
        grand_total            = subtotal,
        validity_days          = validity_days,
        validity_date          = date.today() + timedelta(days=validity_days),
        prepared_by            = prepared_by,
        created_at             = datetime.utcnow(),
        updated_at             = datetime.utcnow(),
    )
    db.session.add(quotation)
    db.session.commit()
    return quotation


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
    installation_charge:    float   = 0.0,
    transport_charge:       float   = 0.0,
    other_charges:          list    | None = None,
    amc_offered:            bool    = False,
    amc_offer_tier:         str     | None = None,
    amc_price:              float   = 0.0,
    warranty_months:        int     = 12,
    warranty_terms_text:    str     | None = None,
) -> Quotation:
    project  = Project.query.filter_by(id=project_id, tenant_id=tenant_id).first()
    if not project:
        raise LookupError('Project not found')

    # Design approval is optional: quote against the approved design when one
    # exists, otherwise generate the quotation before design (no approval link).
    approval = _get_approved_design(tenant_id, project_id)

    # Windows are optional too: a project with no openings yet gets an empty
    # draft that items can be added to afterwards.
    windows = project.windows.all()

    # Versioning
    prior        = get_latest_for_project(tenant_id, project_id)
    new_version  = (prior.quotation_version + 1) if prior else 1
    parent_id    = prior.id if prior else None

    # Supersede any active prior quotation
    if prior and prior.status not in QuotationStatus.TERMINAL:
        prior.status = QuotationStatus.EXPIRED
        db.session.add(prior)

    line_items, subtotal = _build_line_items(windows, tenant_id)

    other_charges = other_charges or []
    install_amt   = Decimal(str(installation_charge or 0))
    transport_amt = Decimal(str(transport_charge or 0))
    amc_amt       = Decimal(str(amc_price or 0)) if amc_offered else Decimal('0')
    other_amt     = sum((Decimal(str(c.get('amount') or 0)) for c in other_charges), Decimal('0'))

    disc_pct    = Decimal(str(discount_pct))
    disc_amount = (subtotal * disc_pct / 100).quantize(Decimal('0.01'))
    taxable     = subtotal - disc_amount + install_amt + transport_amt + amc_amt + other_amt
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
        currency_code           = _tenant_currency(tenant_id),
        project_id              = project_id,
        design_approval_id      = approval.id if approval else None,
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
        installation_charge     = install_amt,
        transport_charge        = transport_amt,
        other_charges_json      = json.dumps(other_charges) if other_charges else None,
        amc_offered              = amc_offered,
        amc_offer_tier          = amc_offer_tier if amc_offered else None,
        amc_price               = amc_amt if amc_offered else None,
        warranty_months         = warranty_months,
        warranty_terms_text     = warranty_terms_text,
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
    acceptance_method: str = 'email',
    accepted_by_name:  str | None = None,
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
    q.accepted_by_name  = (accepted_by_name or '').strip() or q.project.customer_name
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


# ------------------------------------------------------------------ #
#  Totals (used by edit)
# ------------------------------------------------------------------ #

def _recompute_totals(q: Quotation) -> None:
    subtotal = sum(
        (Decimal(str(i.get('amount') or 0)) for i in q.line_items), Decimal('0')
    )
    disc_pct    = Decimal(str(q.discount_pct or 0))
    disc_amount = (subtotal * disc_pct / 100).quantize(Decimal('0.01'))

    amc_amt   = Decimal(str(q.amc_price or 0)) if q.amc_offered else Decimal('0')
    other_amt = sum(
        (Decimal(str(c.get('amount') or 0)) for c in q.other_charges), Decimal('0')
    )

    taxable = (
        subtotal - disc_amount
        + Decimal(str(q.installation_charge or 0))
        + Decimal(str(q.transport_charge or 0))
        + amc_amt
        + other_amt
    )
    tax_amount = (taxable * Decimal(str(q.tax_rate or 0))).quantize(Decimal('0.01'))

    q.subtotal        = subtotal.quantize(Decimal('0.01'))
    q.discount_amount = disc_amount
    q.tax_amount      = tax_amount
    q.grand_total     = (taxable + tax_amount).quantize(Decimal('0.01'))
    q.updated_at      = datetime.utcnow()


# ------------------------------------------------------------------ #
#  Edit quotation  (QUOTE-DRAFT / QUOTE-PENDING_DISCOUNT_APPROVAL only)
# ------------------------------------------------------------------ #

def update_quotation(
    tenant_id:              int,
    quotation_id:           int,
    discount_pct:           float = 0.0,
    validity_days:          int   = DEFAULT_VALIDITY_DAYS,
    payment_terms_template: str   | None = None,
    installation_charge:    float = 0.0,
    transport_charge:       float = 0.0,
    other_charges:          list  | None = None,
    amc_offered:            bool  = False,
    amc_offer_tier:         str   | None = None,
    amc_price:              float = 0.0,
    warranty_months:        int   = 12,
    warranty_terms_text:    str   | None = None,
) -> Quotation:
    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')
    if q.status not in QuotationStatus.EDITABLE:
        raise ValueError('Only draft quotations can be edited.')

    disc = Decimal(str(discount_pct or 0))
    if disc < 0 or disc > 100:
        raise ValueError('Discount must be between 0 and 100.')
    if not validity_days or validity_days < 1:
        raise ValueError('Validity must be at least 1 day.')
    if (Decimal(str(installation_charge or 0)) < 0
            or Decimal(str(transport_charge or 0)) < 0
            or Decimal(str(amc_price or 0)) < 0):
        raise ValueError('Charges cannot be negative.')

    old_disc = Decimal(str(q.discount_pct or 0))

    q.discount_pct           = disc
    q.validity_days          = int(validity_days)
    q.validity_date          = date.today() + timedelta(days=int(validity_days))
    q.payment_terms_template = payment_terms_template or None
    q.installation_charge    = Decimal(str(installation_charge or 0))
    q.transport_charge       = Decimal(str(transport_charge or 0))

    cleaned = [
        {'label': str(c.get('label', '')).strip(), 'amount': float(c.get('amount') or 0)}
        for c in (other_charges or [])
        if str(c.get('label', '')).strip() and c.get('amount')
    ]
    q.other_charges_json = json.dumps(cleaned) if cleaned else None

    q.amc_offered    = bool(amc_offered)
    q.amc_offer_tier = amc_offer_tier if amc_offered else None
    q.amc_price      = Decimal(str(amc_price or 0)) if amc_offered else None

    q.warranty_months     = warranty_months
    q.warranty_terms_text = warranty_terms_text or None

    if disc > DISCOUNT_APPROVAL_THRESHOLD:
        if disc != old_disc or not q.discount_approved:
            q.discount_approved_by = None
            q.discount_approved_at = None
            q.status               = QuotationStatus.PENDING_DISCOUNT_APPROVAL
    else:
        q.discount_approved_by = None
        q.discount_approved_at = None
        q.status               = QuotationStatus.DRAFT

    _recompute_totals(q)
    db.session.commit()
    return q


# ------------------------------------------------------------------ #
#  Delete quotation
# ------------------------------------------------------------------ #

def delete_block_reason(q: Quotation) -> str | None:
    from ...models.order import Order
    if q.status == QuotationStatus.ACCEPTED:
        return 'An accepted quotation cannot be deleted.'
    if Order.query.filter_by(quotation_id=q.id).first():
        return 'This quotation has an order raised against it and cannot be deleted.'
    return None


def delete_quotation(tenant_id: int, quotation_id: int) -> str:
    import os
    from flask import current_app

    q = get_quotation(tenant_id, quotation_id)
    if not q:
        raise LookupError('Quotation not found')

    reason = delete_block_reason(q)
    if reason:
        raise ValueError(reason)

    number         = q.quotation_number
    project        = q.project
    was_flow_draft = q.design_approval_id is None
    pdf_path       = q.pdf_path

    for child in Quotation.query.filter_by(parent_quotation_id=q.id).all():
        child.parent_quotation_id = q.parent_quotation_id

    db.session.delete(q)
    db.session.flush()

    if project is not None and was_flow_draft:
        remaining = Quotation.query.filter_by(project_id=project.id).count()
        if remaining == 0 and project.windows.count() == 0:
            db.session.delete(project)

    db.session.commit()

    if pdf_path:
        full = os.path.join(current_app.config['UPLOAD_FOLDER'], pdf_path)
        try:
            if os.path.isfile(full):
                os.remove(full)
        except OSError:
            pass

    return number


# ================================================================== #
#  MERGE DRAFT QUOTATIONS
# ================================================================== #

MERGE_MIN = 2
MERGE_MAX = 10

MERGE_ARCHIVE = 'archive'
MERGE_DELETE  = 'delete'
MERGE_KEEP    = 'keep'
MERGE_SOURCE_ACTIONS = (MERGE_ARCHIVE, MERGE_DELETE, MERGE_KEEP)

_TWO = Decimal('0.01')


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


# ---------------- candidate search ---------------- #

def _merge_candidate_dict(q: Quotation) -> dict:
    items   = q.line_items
    project = q.project
    return {
        'id':               q.id,
        'quotation_number': q.quotation_number,
        'status':           q.status,
        'status_label':     q.status_label,
        'customer_id':      project.customer_id if project else None,
        'customer_name':    project.customer_name if project else '',
        'project_name':     project.display_name if project else '',
        'item_count':       len(items),
        'labels':           [str(i.get('label') or 'Item') for i in items[:3]],
        'grand_total':      float(q.grand_total) if q.grand_total else 0.0,
        'updated_at':       q.updated_at.isoformat() if q.updated_at else None,
    }


def list_merge_candidates(tenant_id: int, term: str | None = None,
                          customer_id: int | None = None,
                          include_ids: list | None = None,
                          exclude_ids: list | None = None,
                          limit: int = 30) -> list[dict]:
    query = (Quotation.query
             .join(Project, Project.id == Quotation.project_id)
             .filter(Quotation.tenant_id == tenant_id,
                     Quotation.status.in_(list(QuotationStatus.EDITABLE))))

    if customer_id:
        from sqlalchemy import func
        from ...models import Customer
        cust = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
        if cust and (cust.name or '').strip():
            query = query.filter(or_(
                Project.customer_id == customer_id,
                func.lower(func.trim(Project.customer_name)) == cust.name.strip().lower(),
            ))
        else:
            query = query.filter(Project.customer_id == customer_id)
    if exclude_ids:
        query = query.filter(~Quotation.id.in_(exclude_ids))
    if term and term.strip():
        like = f'%{term.strip()}%'
        query = query.filter(or_(
            Quotation.quotation_number.ilike(like),
            Project.customer_name.ilike(like),
            Project.project_name.ilike(like),
            Quotation.line_items_json.ilike(like),
        ))

    rows   = query.order_by(desc(Quotation.updated_at)).limit(limit).all()
    result = [_merge_candidate_dict(r) for r in rows]

    if include_ids:
        present = {r['id'] for r in result}
        missing = [i for i in include_ids if i not in present]
        if missing:
            extra = (Quotation.query
                     .filter(Quotation.tenant_id == tenant_id,
                             Quotation.id.in_(missing),
                             Quotation.status.in_(list(QuotationStatus.EDITABLE)))
                     .all())
            result = [_merge_candidate_dict(r) for r in extra] + result

    return result


def suggest_merge_for(tenant_id: int, quotation_id: int) -> list[dict]:
    q = get_quotation(tenant_id, quotation_id)
    if not q or q.status not in QuotationStatus.EDITABLE:
        return []
    if not q.project or not q.project.customer_id:
        return []
    return list_merge_candidates(
        tenant_id, customer_id=q.project.customer_id, exclude_ids=[q.id]
    )


# ---------------- validation ---------------- #

def _merge_clean_ids(ids) -> list[int]:
    try:
        return list(dict.fromkeys(int(i) for i in (ids or [])))
    except (TypeError, ValueError):
        raise ValueError('Invalid quotation selection.')


def _merge_load_sources(tenant_id: int, ids) -> list[Quotation]:
    ids = _merge_clean_ids(ids)
    if len(ids) < MERGE_MIN:
        raise ValueError(f'Select at least {MERGE_MIN} draft quotations to merge.')
    if len(ids) > MERGE_MAX:
        raise ValueError(f'You can merge at most {MERGE_MAX} quotations at once.')

    rows  = Quotation.query.filter(
        Quotation.tenant_id == tenant_id, Quotation.id.in_(ids)
    ).all()
    by_id = {r.id: r for r in rows}
    if any(i not in by_id for i in ids):
        raise LookupError('One or more selected quotations were not found.')

    ordered = [by_id[i] for i in ids]
    for r in ordered:
        if r.status not in QuotationStatus.EDITABLE:
            raise ValueError(
                f'{r.quotation_number} is "{r.status_label}" and can no longer be merged.'
            )

    # Same customer = same customer record OR same (case-insensitive) name,
    # so duplicate customer records for one person do not block a merge.
    customer_names = {
        ' '.join((r.project.customer_name or '').split()).lower()
        for r in ordered
        if r.project is not None and r.project.customer_id
    }
    customer_names.discard('')
    if len(customer_names) > 1:
        raise ValueError('Selected quotations belong to different customers.')

    return ordered


def _merge_pick_primary(sources: list[Quotation], target_id: int | None) -> Quotation:
    if target_id:
        for s in sources:
            if s.id == int(target_id):
                return s
        raise ValueError('Merge target must be one of the selected quotations.')

    # Base the merged record on the quotation that owns real design data
    # (approved design, or items built from project windows), so the merged
    # quotation stays attached to the right project. Standalone "+ Create Quote"
    # drafts are folded into it.
    for s in sources:
        if s.design_approval_id:
            return s
    for s in sources:
        if any(i.get('window_id') is not None for i in s.line_items):
            return s
    for s in sources:
        if s.project is not None and s.project.customer_id:
            return s
    return sources[0]


# ---------------- combine logic ---------------- #

def _merge_dedupe_key(item: dict):
    if item.get('window_id') is not None:
        return None
    if item.get('style_id') is None and item.get('width_mm') is None:
        return None
    return (
        item.get('style_id'),
        str(item.get('label') or '').strip().lower(),
        item.get('width_mm'),
        item.get('height_mm'),
        item.get('rate_per_sqft'),
        item.get('material'),
        item.get('design_json'),
        item.get('notes') or '',
    )


def _merge_combine(sources: list[Quotation], primary: Quotation, dedupe: bool) -> dict:
    warnings   = []
    items      = []
    index      = {}
    duplicates = 0

    for src in sources:
        for raw in src.line_items:
            item = dict(raw)
            key  = _merge_dedupe_key(item) if dedupe else None

            if key is not None and key in index:
                target = items[index[key]]
                target['qty'] = int(target.get('qty') or 1) + int(item.get('qty') or 1)
                target['amount'] = float(
                    (_dec(target.get('amount')) + _dec(item.get('amount'))).quantize(_TWO)
                )
                duplicates += 1
                continue

            item['line_id']     = len(items) + 1
            item['merged_from'] = src.quotation_number
            items.append(item)
            if key is not None:
                index[key] = len(items) - 1

    if duplicates:
        warnings.append(f'{duplicates} identical line item(s) were combined by quantity.')

    installation = sum((_dec(s.installation_charge) for s in sources), Decimal('0'))
    transport    = sum((_dec(s.transport_charge)    for s in sources), Decimal('0'))

    other_charges = []
    for s in sources:
        other_charges.extend(s.other_charges)

    amc_sources = [s for s in sources if s.amc_offered]
    amc_offered = bool(amc_sources)
    amc_price   = sum((_dec(s.amc_price) for s in amc_sources), Decimal('0'))
    amc_tier    = None
    if amc_sources:
        def _rank(tier):
            try:
                return AmcTier.ALL.index(tier)
            except ValueError:
                return -1
        amc_tier = max((s.amc_offer_tier for s in amc_sources), key=_rank)
        if len(amc_sources) > 1:
            warnings.append('AMC prices from multiple quotations were added together.')

    sub_total  = Decimal('0')
    disc_total = Decimal('0')
    for s in sources:
        sub = sum((_dec(i.get('amount')) for i in s.line_items), Decimal('0'))
        sub_total  += sub
        disc_total += sub * _dec(s.discount_pct) / 100
    discount_pct = (
        (disc_total / sub_total * 100).quantize(_TWO) if sub_total else Decimal('0.00')
    )
    if len({_dec(s.discount_pct) for s in sources}) > 1:
        warnings.append('Different discounts were blended into one weighted-average discount.')

    if len({_dec(s.tax_rate) for s in sources}) > 1:
        warnings.append(f"Tax rates differ; using {primary.quotation_number}'s rate.")

    payment_terms = next((s.payment_terms_template for s in sources if s.payment_terms_template), None)
    warranty_text = next((s.warranty_terms_text    for s in sources if s.warranty_terms_text), None)

    return {
        'line_items':             items,
        'duplicates_merged':      duplicates,
        'installation_charge':    installation,
        'transport_charge':       transport,
        'other_charges':          other_charges,
        'amc_offered':            amc_offered,
        'amc_offer_tier':         amc_tier,
        'amc_price':              amc_price,
        'discount_pct':           discount_pct,
        'tax_rate':               _dec(primary.tax_rate),
        'payment_terms_template': payment_terms,
        'warranty_months':        max((s.warranty_months or 0 for s in sources), default=12) or 12,
        'warranty_terms_text':    warranty_text,
        'validity_days':          max((s.validity_days or 0 for s in sources), default=30) or 30,
        'warnings':               warnings,
    }


def _merge_totals(p: dict) -> dict:
    subtotal    = sum((_dec(i.get('amount')) for i in p['line_items']), Decimal('0'))
    disc_amount = (subtotal * p['discount_pct'] / 100).quantize(_TWO)
    amc_amt     = p['amc_price'] if p['amc_offered'] else Decimal('0')
    other_amt   = sum((_dec(c.get('amount')) for c in p['other_charges']), Decimal('0'))
    taxable     = (subtotal - disc_amount + p['installation_charge']
                   + p['transport_charge'] + amc_amt + other_amt)
    tax_amount  = (taxable * p['tax_rate']).quantize(_TWO)
    return {
        'subtotal':        subtotal.quantize(_TWO),
        'discount_amount': disc_amount,
        'tax_amount':      tax_amount,
        'grand_total':     (taxable + tax_amount).quantize(_TWO),
        'other_amount':    other_amt.quantize(_TWO),
    }


# ---------------- preview (no DB writes) ---------------- #

def preview_merge(tenant_id: int, ids, dedupe: bool = True,
                  target_id: int | None = None) -> dict:
    sources = _merge_load_sources(tenant_id, ids)
    primary = _merge_pick_primary(sources, target_id)
    payload = _merge_combine(sources, primary, dedupe)
    totals  = _merge_totals(payload)

    return {
        'sources':             [{'id': s.id, 'number': s.quotation_number} for s in sources],
        'primary_number':      primary.quotation_number,
        'item_count':          len(payload['line_items']),
        'duplicates_merged':   payload['duplicates_merged'],
        'subtotal':            float(totals['subtotal']),
        'discount_pct':        float(payload['discount_pct']),
        'discount_amount':     float(totals['discount_amount']),
        'installation_charge': float(payload['installation_charge']),
        'transport_charge':    float(payload['transport_charge']),
        'other_amount':        float(totals['other_amount']),
        'amc_price':           float(payload['amc_price']) if payload['amc_offered'] else 0.0,
        'tax_rate':            float(payload['tax_rate']),
        'tax_amount':          float(totals['tax_amount']),
        'grand_total':         float(totals['grand_total']),
        'needs_discount_approval': payload['discount_pct'] > DISCOUNT_APPROVAL_THRESHOLD,
        'warnings':            payload['warnings'],
    }


# ---------------- merge ---------------- #

def _merge_next_version(project_id: int) -> int:
    versions = [
        v for (v,) in db.session.query(Quotation.quotation_version)
        .filter(Quotation.project_id == project_id).all()
    ]
    return (max(versions) if versions else 0) + 1


def _merge_apply(q: Quotation, p: dict, totals: dict, status: str) -> None:
    q.line_items_json        = json.dumps(p['line_items'])
    q.subtotal               = totals['subtotal']
    q.discount_pct           = p['discount_pct']
    q.discount_amount        = totals['discount_amount']
    q.discount_approved_by   = None
    q.discount_approved_at   = None
    q.tax_rate               = p['tax_rate']
    q.tax_amount             = totals['tax_amount']
    q.grand_total            = totals['grand_total']
    q.installation_charge    = p['installation_charge']
    q.transport_charge       = p['transport_charge']
    q.other_charges_json     = json.dumps(p['other_charges']) if p['other_charges'] else None
    q.amc_offered            = p['amc_offered']
    q.amc_offer_tier         = p['amc_offer_tier'] if p['amc_offered'] else None
    q.amc_price              = p['amc_price'] if p['amc_offered'] else None
    q.payment_terms_template = p['payment_terms_template']
    q.warranty_months        = p['warranty_months']
    q.warranty_terms_text    = p['warranty_terms_text']
    q.validity_days          = p['validity_days']
    q.validity_date          = date.today() + timedelta(days=p['validity_days'])
    q.status                 = status
    q.updated_at             = datetime.utcnow()


def _merge_note(q: Quotation, text: str) -> None:
    q.negotiation_notes = f'{q.negotiation_notes}\n{text}' if q.negotiation_notes else text


def merge_quotations(tenant_id: int, user_id: int, ids,
                     target_id: int | None = None,
                     dedupe: bool = True,
                     source_action: str = MERGE_ARCHIVE) -> Quotation:
    if source_action not in MERGE_SOURCE_ACTIONS:
        raise ValueError('Invalid source action.')

    sources = _merge_load_sources(tenant_id, ids)
    primary = _merge_pick_primary(sources, target_id)
    payload = _merge_combine(sources, primary, dedupe)
    totals  = _merge_totals(payload)

    status = (
        QuotationStatus.PENDING_DISCOUNT_APPROVAL
        if payload['discount_pct'] > DISCOUNT_APPROVAL_THRESHOLD
        else QuotationStatus.DRAFT
    )

    source_numbers = ', '.join(s.quotation_number for s in sources)

    if target_id:
        result = primary
    else:
        result = Quotation(
            tenant_id          = tenant_id,
            currency_code      = _tenant_currency(tenant_id),
            project_id         = primary.project_id,
            design_approval_id = primary.design_approval_id,
            quotation_number   = Quotation.generate_number(tenant_id),
            quotation_version  = _merge_next_version(primary.project_id),
            status             = QuotationStatus.DRAFT,
            prepared_by        = user_id,
            created_at         = datetime.utcnow(),
            updated_at         = datetime.utcnow(),
        )
        db.session.add(result)

    _merge_apply(result, payload, totals, status)
    _merge_note(result, f'Merged from: {source_numbers}')
    db.session.flush()

    others = [s for s in sources if s.id != result.id]

    if source_action == MERGE_ARCHIVE:
        for s in others:
            s.status = QuotationStatus.EXPIRED
            _merge_note(s, f'Merged into {result.quotation_number}')
            s.updated_at = datetime.utcnow()

    db.session.commit()

    if source_action == MERGE_DELETE:
        for s in others:
            try:
                delete_quotation(tenant_id, s.id)
            except (ValueError, LookupError):
                fresh = get_quotation(tenant_id, s.id)
                if fresh:
                    fresh.status = QuotationStatus.EXPIRED
                    _merge_note(fresh, f'Merged into {result.quotation_number}')
                    db.session.commit()

    return result