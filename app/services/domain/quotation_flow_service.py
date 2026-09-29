import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import current_app, url_for

from ...extensions import db
from ...models import Customer, Project
from ...models.product import ProductSeries, WindowStyle
from ...models.project import ProjectStatus
from ...models.quotation import Quotation, QuotationStatus

WALK_IN_NAME = 'Walk-In Customer'
DEFAULT_TAX_RATE = Decimal('0.20')
DEFAULT_VALIDITY_DAYS = 30
DEFAULT_RATE_PER_SQFT = Decimal('0')
SQMM_PER_SQFT = Decimal('92903.04')


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_draft(tenant_id: int, quotation_id: int) -> Quotation | None:
    q = Quotation.query.filter_by(id=quotation_id, tenant_id=tenant_id).first()
    if q and q.status in QuotationStatus.EDITABLE:
        return q
    return None


def is_walk_in(quotation: Quotation) -> bool:
    return quotation.project is not None and quotation.project.customer_id is None


def search_customers(tenant_id: int, term: str | None, limit: int = 20) -> list[Customer]:
    q = Customer.query.filter_by(tenant_id=tenant_id)
    if term:
        like = f'%{term.strip()}%'
        q = q.filter(db.or_(
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
            Customer.email.ilike(like),
        ))
    return q.order_by(Customer.name).limit(limit).all()


CATALOG_PDF_DIR = 'catalog_pdfs'


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')


def _find_pdf(style: WindowStyle, series: ProductSeries) -> str | None:
    """
    Convention-based lookup (no DB change). Files live in
    app/static/catalog_pdfs/ and are matched in this order:
      1. style-<style_id>.pdf
      2. <style-name-slug>.pdf
      3. series-<series_id>.pdf
      4. <series-name-slug>.pdf
    """
    base = os.path.join(current_app.static_folder, CATALOG_PDF_DIR)
    candidates = [
        f'style-{style.id}.pdf',
        f'{_slug(style.name)}.pdf',
        f'series-{series.id}.pdf',
        f'{_slug(series.name)}.pdf',
    ]
    for fname in candidates:
        if fname and os.path.isfile(os.path.join(base, fname)):
            return url_for('static', filename=f'{CATALOG_PDF_DIR}/{fname}')
    return None


def list_gallery(tenant_id: int) -> list[dict]:
    series_rows = (ProductSeries.query
                   .filter_by(tenant_id=tenant_id, is_active=True)
                   .order_by(ProductSeries.name)
                   .all())
    gallery = []
    for series in series_rows:
        styles = series.styles.order_by(WindowStyle.sort_order, WindowStyle.name).all()
        style_dicts = []
        for s in styles:
            d = s.to_dict()
            d['pdf_url'] = _find_pdf(s, series)
            style_dicts.append(d)
        gallery.append({
            'series': series.to_dict(),
            'styles': style_dicts,
        })
    return gallery


def get_style(tenant_id: int, style_id: int) -> tuple[WindowStyle, ProductSeries] | None:
    style = WindowStyle.query.filter_by(id=style_id).first()
    if not style:
        return None
    series = ProductSeries.query.filter_by(id=style.series_id, tenant_id=tenant_id).first()
    if not series:
        return None
    return style, series


# ------------------------------------------------------------------ #
#  Draft creation (Step 2 → Step 3)
# ------------------------------------------------------------------ #

def create_draft(tenant_id: int, user_id: int, customer_id: int | None = None) -> Quotation:
    customer = None
    if customer_id:
        customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
        if not customer:
            raise LookupError('Customer not found')

    project = Project(
        tenant_id=tenant_id,
        created_by=user_id,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else WALK_IN_NAME,
        project_name=None,
        address=customer.address if customer else None,
        status=ProjectStatus.DRAFT,
    )
    db.session.add(project)
    db.session.flush()

    quotation = Quotation(
        tenant_id=tenant_id,
        project_id=project.id,
        design_approval_id=None,
        quotation_number=Quotation.generate_number(tenant_id),
        quotation_version=1,
        status=QuotationStatus.DRAFT,
        line_items_json=json.dumps([]),
        subtotal=Decimal('0'),
        discount_pct=Decimal('0'),
        discount_amount=Decimal('0'),
        tax_rate=DEFAULT_TAX_RATE,
        tax_amount=Decimal('0'),
        grand_total=Decimal('0'),
        validity_days=DEFAULT_VALIDITY_DAYS,
        validity_date=date.today() + timedelta(days=DEFAULT_VALIDITY_DAYS),
        prepared_by=user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(quotation)
    db.session.commit()
    return quotation


def create_customer_and_draft(tenant_id: int, user_id: int, name: str,
                              phone=None, email=None, city=None, address=None) -> Quotation:
    from . import customer_service
    customer = customer_service.create_customer(
        tenant_id, name, phone=phone, email=email, city=city, address=address
    )
    return create_draft(tenant_id, user_id, customer_id=customer.id)


# ------------------------------------------------------------------ #
#  Totals
# ------------------------------------------------------------------ #

def recompute_totals(quotation: Quotation) -> Quotation:
    items = quotation.line_items
    subtotal = sum((_d(i.get('amount')) for i in items), Decimal('0'))
    disc_pct = _d(quotation.discount_pct)
    disc_amount = (subtotal * disc_pct / 100).quantize(Decimal('0.01'))
    taxable = (
        subtotal - disc_amount
        + _d(quotation.installation_charge)
        + _d(quotation.transport_charge)
    )
    tax_amount = (taxable * _d(quotation.tax_rate)).quantize(Decimal('0.01'))

    quotation.subtotal = subtotal.quantize(Decimal('0.01'))
    quotation.discount_amount = disc_amount
    quotation.tax_amount = tax_amount
    quotation.grand_total = (taxable + tax_amount).quantize(Decimal('0.01'))
    quotation.updated_at = datetime.utcnow()
    return quotation


# ------------------------------------------------------------------ #
#  Line items (Step 3 ⇄ Step 4 loop)
# ------------------------------------------------------------------ #

def add_line_item(
    tenant_id: int,
    quotation_id: int,
    style_id: int | None,
    label: str,
    width_mm: int,
    height_mm: int,
    qty: int = 1,
    rate_per_sqft: float = 0.0,
    source: str = 'gallery',
    notes: str | None = None,
    design_json: str | None = None,
) -> Quotation:
    quotation = get_draft(tenant_id, quotation_id)
    if not quotation:
        raise LookupError('Draft quotation not found or no longer editable')

    if width_mm <= 0 or height_mm <= 0:
        raise ValueError('Width and height must be greater than zero')
    if qty <= 0:
        raise ValueError('Quantity must be at least 1')
    if source not in ('gallery', 'configurator'):
        raise ValueError('Invalid product source')

    series_name = None
    style_name = None
    material = None
    if style_id:
        found = get_style(tenant_id, style_id)
        if not found:
            raise LookupError('Product style not found')
        style, series = found
        style_name = style.name
        series_name = series.name
        material = series.material

    area_sqft = (Decimal(width_mm) * Decimal(height_mm) / SQMM_PER_SQFT).quantize(Decimal('0.0001'))
    rate = _d(rate_per_sqft)
    unit_total = (area_sqft * rate).quantize(Decimal('0.01'))
    amount = (unit_total * Decimal(qty)).quantize(Decimal('0.01'))

    items = quotation.line_items
    items.append({
        'line_id':      (max((i.get('line_id', 0) for i in items), default=0) + 1),
        'source':       source,
        'style_id':     style_id,
        'series':       series_name,
        'style':        style_name,
        'label':        (label or style_name or 'Item').strip(),
        'material':     material,
        'width_mm':     int(width_mm),
        'height_mm':    int(height_mm),
        'area_sqft':    float(area_sqft),
        'rate_per_sqft': float(rate),
        'qty':          int(qty),
        'unit':         'nos',
        'unit_total':   float(unit_total),
        'amount':       float(amount),
        'notes':        notes or '',
        'design_json':  design_json,
    })

    quotation.line_items_json = json.dumps(items)
    recompute_totals(quotation)
    db.session.commit()
    return quotation


def remove_line_item(tenant_id: int, quotation_id: int, line_id: int) -> Quotation:
    quotation = get_draft(tenant_id, quotation_id)
    if not quotation:
        raise LookupError('Draft quotation not found or no longer editable')

    items = [i for i in quotation.line_items if i.get('line_id') != line_id]
    quotation.line_items_json = json.dumps(items)
    recompute_totals(quotation)
    db.session.commit()
    return quotation


# ------------------------------------------------------------------ #
#  Proceed to Quotation (Step 3 → Step 5)
# ------------------------------------------------------------------ #

def proceed_to_quotation(tenant_id: int, quotation_id: int) -> Quotation:
    quotation = get_draft(tenant_id, quotation_id)
    if not quotation:
        raise LookupError('Draft quotation not found or no longer editable')
    if not quotation.line_items:
        raise ValueError('Add at least one product before proceeding')

    recompute_totals(quotation)
    db.session.commit()
    return quotation
