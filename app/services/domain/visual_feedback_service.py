"""Customer approve / change-request handling for the visualiser link.

Rules
-----
* The customer can only view, approve and comment. Nothing here edits an item,
  its options or its price.
* An approval stores a fingerprint of the item as the customer saw it. When the
  salesperson changes the item the fingerprint no longer matches and the
  approval is superseded, so the customer is asked to review again.
* A quotation is ready to lock when every item has an active approval and no
  change request is open.
"""
import hashlib
import json
from datetime import datetime

from ...extensions import db
from ...models.quotation import Quotation, QuotationStatus
from ...models.visual_feedback import (
    VisualFeedback, VisualFeedbackKind, VisualFeedbackStatus,
)

MAX_COMMENT_LEN = 1000
MAX_OPEN_REQUESTS = 25

# keys that change without the item itself changing
_VOLATILE_KEYS = {'merged_from', 'line_id'}

# statuses where the customer may still respond
_CLOSED_STATUSES = set(QuotationStatus.TERMINAL) | {QuotationStatus.EXPIRED}


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def line_key(item: dict, index: int) -> int:
    """Stable integer id for a quotation line item."""
    for name in ('line_id', 'window_id', 'opening_id'):
        value = item.get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return index + 1


def item_fingerprint(item: dict) -> str:
    """Hash of everything the customer sees or pays for on this item."""
    payload = {k: v for k, v in item.items() if k not in _VOLATILE_KEYS}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _get_quotation(tenant_id: int, quotation_id: int) -> Quotation:
    q = Quotation.query.filter_by(id=quotation_id, tenant_id=tenant_id).first()
    if not q:
        raise LookupError('Quotation not found.')
    return q


def _items(q: Quotation) -> dict[int, dict]:
    """{line_id: item} for the quotation's current line items."""
    return {line_key(item, i): item for i, item in enumerate(q.line_items)}


def _ensure_open_for_customer(q: Quotation) -> None:
    if q.status in _CLOSED_STATUSES:
        raise ValueError('This quotation is closed and can no longer be changed.')


def _record_link_response(share_link, action: str) -> None:
    if share_link is None:
        return
    share_link.responded_at = datetime.utcnow()
    share_link.response_action = action


# ------------------------------------------------------------------ #
#  Approval validity
# ------------------------------------------------------------------ #

def refresh_approvals(tenant_id: int, quotation_id: int, commit: bool = True) -> int:
    """Supersede approvals whose item changed since the customer approved it.

    Call this after staff edit an item, and on every read of the customer link.
    Returns the number of approvals that were superseded.
    """
    q = _get_quotation(tenant_id, quotation_id)
    current = {lid: item_fingerprint(item) for lid, item in _items(q).items()}

    active = VisualFeedback.query.filter_by(
        tenant_id=tenant_id, quotation_id=quotation_id,
        kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE,
    ).all()

    superseded = 0
    now = datetime.utcnow()
    item_changed = False
    for row in active:
        if row.line_id is None:
            continue
        if current.get(row.line_id) != row.item_hash:
            row.status = VisualFeedbackStatus.SUPERSEDED
            row.superseded_at = now
            superseded += 1
            item_changed = True

    if item_changed:
        # a whole-quote approval is only valid while every item approval is
        for row in active:
            if row.line_id is None and row.status == VisualFeedbackStatus.ACTIVE:
                row.status = VisualFeedbackStatus.SUPERSEDED
                row.superseded_at = now
                superseded += 1

    if superseded and commit:
        db.session.commit()
    return superseded


# ------------------------------------------------------------------ #
#  Customer actions
# ------------------------------------------------------------------ #

def approve_item(tenant_id: int, quotation_id: int, line_id: int,
                 share_link=None, author_name: str | None = None) -> VisualFeedback:
    q = _get_quotation(tenant_id, quotation_id)
    _ensure_open_for_customer(q)
    refresh_approvals(tenant_id, quotation_id, commit=False)

    items = _items(q)
    if line_id not in items:
        raise LookupError('Item not found on this quotation.')

    open_request = VisualFeedback.query.filter_by(
        tenant_id=tenant_id, quotation_id=quotation_id, line_id=line_id,
        kind=VisualFeedbackKind.CHANGE_REQUEST, status=VisualFeedbackStatus.OPEN,
    ).first()
    if open_request:
        raise ValueError('This item has an open change request. '
                         'Please wait for the update before approving.')

    # replace any earlier active approval for this item
    for old in VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id, line_id=line_id,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all():
        old.status = VisualFeedbackStatus.SUPERSEDED
        old.superseded_at = datetime.utcnow()

    row = VisualFeedback(
        tenant_id=tenant_id, quotation_id=quotation_id,
        share_link_id=share_link.id if share_link else None,
        line_id=line_id,
        kind=VisualFeedbackKind.APPROVED,
        status=VisualFeedbackStatus.ACTIVE,
        item_hash=item_fingerprint(items[line_id]),
        author_name=(author_name or '').strip()[:120] or None,
    )
    db.session.add(row)

    if _all_items_approved(tenant_id, quotation_id, pending=row, items=items):
        _record_link_response(share_link, 'APPROVED')

    db.session.commit()
    return row


def approve_all(tenant_id: int, quotation_id: int, share_link=None,
                author_name: str | None = None) -> list[VisualFeedback]:
    q = _get_quotation(tenant_id, quotation_id)
    _ensure_open_for_customer(q)
    refresh_approvals(tenant_id, quotation_id, commit=False)

    items = _items(q)
    if not items:
        raise ValueError('There are no items to approve.')

    if open_request_count(tenant_id, quotation_id):
        raise ValueError('There are open change requests. '
                         'Please wait for the update before approving everything.')

    now = datetime.utcnow()
    name = (author_name or '').strip()[:120] or None
    link_id = share_link.id if share_link else None

    for old in VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all():
        old.status = VisualFeedbackStatus.SUPERSEDED
        old.superseded_at = now

    rows = []
    for lid, item in items.items():
        rows.append(VisualFeedback(
            tenant_id=tenant_id, quotation_id=quotation_id, share_link_id=link_id,
            line_id=lid, kind=VisualFeedbackKind.APPROVED,
            status=VisualFeedbackStatus.ACTIVE,
            item_hash=item_fingerprint(item), author_name=name,
        ))
    rows.append(VisualFeedback(
        tenant_id=tenant_id, quotation_id=quotation_id, share_link_id=link_id,
        line_id=None, kind=VisualFeedbackKind.APPROVED,
        status=VisualFeedbackStatus.ACTIVE, author_name=name,
    ))
    db.session.add_all(rows)
    _record_link_response(share_link, 'APPROVED')
    db.session.commit()
    return rows


def add_change_request(tenant_id: int, quotation_id: int, line_id: int | None,
                       comment: str, share_link=None,
                       author_name: str | None = None) -> VisualFeedback:
    q = _get_quotation(tenant_id, quotation_id)
    _ensure_open_for_customer(q)

    text = (comment or '').strip()
    if not text:
        raise ValueError('Please describe the change you would like.')
    if len(text) > MAX_COMMENT_LEN:
        raise ValueError(f'Please keep your comment under {MAX_COMMENT_LEN} characters.')

    items = _items(q)
    if line_id is not None and line_id not in items:
        raise LookupError('Item not found on this quotation.')

    if open_request_count(tenant_id, quotation_id) >= MAX_OPEN_REQUESTS:
        raise ValueError('Too many open change requests. Your salesperson will be in touch.')

    now = datetime.utcnow()
    # a change request withdraws the customer's approval of that item
    if line_id is not None:
        approvals = VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id, line_id=line_id,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all()
    else:
        approvals = VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all()
    for old in approvals:
        old.status = VisualFeedbackStatus.SUPERSEDED
        old.superseded_at = now
    # and any whole-quote approval
    for old in VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id, line_id=None,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all():
        old.status = VisualFeedbackStatus.SUPERSEDED
        old.superseded_at = now

    row = VisualFeedback(
        tenant_id=tenant_id, quotation_id=quotation_id,
        share_link_id=share_link.id if share_link else None,
        line_id=line_id,
        kind=VisualFeedbackKind.CHANGE_REQUEST,
        status=VisualFeedbackStatus.OPEN,
        comment=text,
        author_name=(author_name or '').strip()[:120] or None,
    )
    db.session.add(row)
    _record_link_response(share_link, 'CHANGES_REQUESTED')
    db.session.commit()
    return row


# ------------------------------------------------------------------ #
#  Staff actions
# ------------------------------------------------------------------ #

def resolve_request(tenant_id: int, feedback_id: int, user_id: int,
                    note: str | None = None) -> VisualFeedback:
    row = VisualFeedback.query.filter_by(id=feedback_id, tenant_id=tenant_id).first()
    if not row or row.kind != VisualFeedbackKind.CHANGE_REQUEST:
        raise LookupError('Change request not found.')
    if row.status == VisualFeedbackStatus.RESOLVED:
        return row

    now = datetime.utcnow()
    row.status = VisualFeedbackStatus.RESOLVED
    row.resolved_at = now
    row.resolved_by = user_id

    reply = (note or '').strip()
    if reply:
        db.session.add(VisualFeedback(
            tenant_id=tenant_id, quotation_id=row.quotation_id,
            share_link_id=row.share_link_id, line_id=row.line_id,
            kind=VisualFeedbackKind.STAFF_REPLY,
            status=VisualFeedbackStatus.RESOLVED,
            comment=reply[:MAX_COMMENT_LEN],
            author_user_id=user_id,
        ))
    db.session.commit()
    return row


# ------------------------------------------------------------------ #
#  Read models
# ------------------------------------------------------------------ #

def open_request_count(tenant_id: int, quotation_id: int) -> int:
    return VisualFeedback.query.filter_by(
        tenant_id=tenant_id, quotation_id=quotation_id,
        kind=VisualFeedbackKind.CHANGE_REQUEST, status=VisualFeedbackStatus.OPEN,
    ).count()


def _all_items_approved(tenant_id: int, quotation_id: int,
                        pending: VisualFeedback | None = None,
                        items: dict | None = None) -> bool:
    if items is None:
        items = _items(_get_quotation(tenant_id, quotation_id))
    if not items:
        return False
    approved = {
        r.line_id for r in VisualFeedback.query.filter_by(
            tenant_id=tenant_id, quotation_id=quotation_id,
            kind=VisualFeedbackKind.APPROVED, status=VisualFeedbackStatus.ACTIVE).all()
        if r.line_id is not None
    }
    if pending is not None and pending.line_id is not None:
        approved.add(pending.line_id)
    return all(lid in approved for lid in items)


def summary(tenant_id: int, quotation_id: int) -> dict:
    """Per-item state used by both the customer page and the staff inbox."""
    refresh_approvals(tenant_id, quotation_id)
    q = _get_quotation(tenant_id, quotation_id)
    items = _items(q)

    rows = (VisualFeedback.query
            .filter_by(tenant_id=tenant_id, quotation_id=quotation_id)
            .order_by(VisualFeedback.created_at.asc()).all())

    per_item = {}
    for lid, item in items.items():
        per_item[lid] = {
            'line_id':   lid,
            'label':     item.get('label') or 'Item',
            'approved':  False,
            'needs_review': False,     # approved earlier, changed since
            'open_requests': [],
            'thread':    [],
        }

    for r in rows:
        if r.line_id is None or r.line_id not in per_item:
            continue
        slot = per_item[r.line_id]
        if r.kind == VisualFeedbackKind.APPROVED:
            if r.status == VisualFeedbackStatus.ACTIVE:
                slot['approved'] = True
            elif r.status == VisualFeedbackStatus.SUPERSEDED and not slot['approved']:
                slot['needs_review'] = True
        else:
            slot['thread'].append(r.to_dict())
            if r.is_open:
                slot['open_requests'].append(r.to_dict())

    general_open = [r.to_dict() for r in rows if r.line_id is None and r.is_open]
    open_count = sum(len(s['open_requests']) for s in per_item.values()) + len(general_open)
    all_approved = bool(per_item) and all(s['approved'] for s in per_item.values())

    return {
        'quotation_id':   quotation_id,
        'items':          list(per_item.values()),
        'general_open':   general_open,
        'open_count':     open_count,
        'all_approved':   all_approved,
        'ready_to_lock':  all_approved and open_count == 0,
    }


def inbox(tenant_id: int, quotation_id: int | None = None, only_open: bool = True) -> list[dict]:
    """Change requests for the staff feedback inbox."""
    query = VisualFeedback.query.filter_by(
        tenant_id=tenant_id, kind=VisualFeedbackKind.CHANGE_REQUEST)
    if quotation_id is not None:
        query = query.filter_by(quotation_id=quotation_id)
    if only_open:
        query = query.filter_by(status=VisualFeedbackStatus.OPEN)

    result = []
    for row in query.order_by(VisualFeedback.created_at.desc()).limit(200).all():
        data = row.to_dict()
        data['quotation_id'] = row.quotation_id
        label = None
        if row.line_id is not None:
            q = Quotation.query.filter_by(id=row.quotation_id, tenant_id=tenant_id).first()
            if q:
                item = _items(q).get(row.line_id)
                label = item.get('label') if item else None
        data['item_label'] = label or ('Whole quotation' if row.line_id is None else 'Item')
        result.append(data)
    return result
