"""
Master Quotation sections.

Resolution order (later wins):
  1. built-in defaults (SECTIONS)
  2. tenant default template   (MasterQuoteConfig.quotation_id IS NULL)
  3. per-quotation override    (MasterQuoteConfig.quotation_id = <id>)

Required sections can never be switched off.
"""
import json
from datetime import datetime

from ...extensions import db
from ...models.master_quote_config import MasterQuoteConfig

# key, label, help text, default on, required
SECTIONS = [
    {'key': 'visual',        'label': 'Visual preview on the house',
     'help': 'Customer sees how doors and windows will look, with the visualizer link.',
     'default': True,  'required': False},
    {'key': 'items',         'label': 'Items, material, colour and size',
     'help': 'Every product with its material, colour and size.',
     'default': True,  'required': True},
    {'key': 'pricing',       'label': 'Pricing and totals',
     'help': 'Item prices, charges, tax and grand total.',
     'default': True,  'required': True},
    {'key': 'payment_stages', 'label': 'Payment stages',
     'help': 'Advance, Pre-Dispatch, On-Installation and Retention.',
     'default': True,  'required': False},
    {'key': 'manufacturing', 'label': 'Factory steps',
     'help': 'Cutting, Machining, Assembly, Glazing and Quality Check.',
     'default': True,  'required': False},
    {'key': 'terms',         'label': 'Terms and warranty',
     'help': 'Payment terms, warranty months and warranty text.',
     'default': True,  'required': False},
    {'key': 'scope',         'label': 'Overview and scope of work',
     'help': 'Short written overview at the top of the PDF.',
     'default': True,  'required': False},
    {'key': 'progress',      'label': 'Live progress',
     'help': 'Customer follows order, payment, production and delivery.',
     'default': True,  'required': False},
]

KEYS = [s['key'] for s in SECTIONS]
REQUIRED = {s['key'] for s in SECTIONS if s['required']}


def defaults() -> dict:
    return {s['key']: s['default'] for s in SECTIONS}


def _clean(raw: dict) -> dict:
    out = {}
    for key in KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    for key in REQUIRED:
        out[key] = True
    return out


def _row(tenant_id: int, quotation_id: int | None):
    return MasterQuoteConfig.query.filter_by(
        tenant_id=tenant_id, quotation_id=quotation_id).first()


def tenant_default(tenant_id: int) -> dict:
    merged = defaults()
    row = _row(tenant_id, None)
    if row:
        merged.update(_clean(row.sections))
    return _clean(merged)


def has_override(tenant_id: int, quotation_id: int) -> bool:
    return _row(tenant_id, quotation_id) is not None


def get_sections(tenant_id: int, quotation_id: int) -> dict:
    """Effective on/off map for one quotation."""
    merged = tenant_default(tenant_id)
    row = _row(tenant_id, quotation_id)
    if row:
        merged.update(_clean(row.sections))
    return _clean(merged)


def _save(tenant_id: int, quotation_id: int | None, selected: set, user_id: int | None) -> dict:
    data = _clean({key: (key in selected) for key in KEYS})
    row = _row(tenant_id, quotation_id)
    if row is None:
        row = MasterQuoteConfig(
            tenant_id=tenant_id, quotation_id=quotation_id,
            created_at=datetime.utcnow())
        db.session.add(row)
    row.sections_json = json.dumps(data)
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return data


def save_for_quotation(tenant_id: int, quotation_id: int, selected, user_id: int | None = None) -> dict:
    from .quotation_service import get_quotation
    if not get_quotation(tenant_id, quotation_id):
        raise LookupError('Quotation not found')
    return _save(tenant_id, quotation_id, set(selected or []), user_id)


def save_tenant_default(tenant_id: int, selected, user_id: int | None = None) -> dict:
    return _save(tenant_id, None, set(selected or []), user_id)


def reset_quotation(tenant_id: int, quotation_id: int) -> None:
    """Drop the override so the quotation follows the tenant default again."""
    row = _row(tenant_id, quotation_id)
    if row:
        db.session.delete(row)
        db.session.commit()


def form_rows(tenant_id: int, quotation_id: int) -> list[dict]:
    """Catalogue merged with the current on/off state, for the staff form."""
    current = get_sections(tenant_id, quotation_id)
    return [dict(s, enabled=current.get(s['key'], s['default'])) for s in SECTIONS]
