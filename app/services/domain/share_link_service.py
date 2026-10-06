from datetime import datetime

from ...extensions import db
from ...models.share_link import ShareLink, ShareLinkType


def get_latest(tenant_id: int, resource_type: str, resource_id: int):
    """Most recent link for a resource (active or not), for status display."""
    return (
        ShareLink.query
        .filter_by(tenant_id=tenant_id, resource_type=resource_type, resource_id=resource_id)
        .order_by(ShareLink.created_at.desc(), ShareLink.id.desc())
        .first()
    )


def get_or_create_link(
    tenant_id: int,
    resource_type: str,
    resource_id: int,
    created_by: int | None = None,
    ttl_days: int | None = None,
    force_new: bool = False,
) -> ShareLink:
    """Reuse the current active link so the sales user always copies the same
    URL; create a fresh one when none is active or force_new is set
    (force_new revokes the previous link)."""
    if resource_type not in ShareLinkType.ALL:
        raise ValueError(f'Unsupported share link type: {resource_type}')

    current = get_latest(tenant_id, resource_type, resource_id)

    if current and current.is_active and not force_new:
        return current

    if current and current.is_active and force_new:
        current.revoked_at = datetime.utcnow()

    link = ShareLink(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        token=ShareLink.new_token(),
        created_by=created_by,
        expires_at=ShareLink.default_expiry(ttl_days),
    )
    db.session.add(link)
    db.session.commit()
    return link


# Backward-compatible alias for older callers
get_or_create = get_or_create_link


def get_by_token(token: str):
    if not token:
        return None
    return ShareLink.query.filter_by(token=token).first()


def get_active_by_token(token: str):
    """Returns the link only if it exists, is not revoked and not expired."""
    link = get_by_token(token)
    if not link or not link.is_active:
        return None
    return link


def record_open(link: ShareLink) -> None:
    now = datetime.utcnow()
    if not link.first_opened_at:
        link.first_opened_at = now
    link.last_opened_at = now
    link.open_count = (link.open_count or 0) + 1
    db.session.commit()


def record_response(link: ShareLink, action: str) -> None:
    link.responded_at = datetime.utcnow()
    link.response_action = action
    db.session.commit()


def revoke(tenant_id: int, link_id: int) -> ShareLink:
    link = ShareLink.query.filter_by(id=link_id, tenant_id=tenant_id).first()
    if not link:
        raise LookupError('Share link not found')
    if not link.revoked_at:
        link.revoked_at = datetime.utcnow()
        db.session.commit()
    return link


def extend(tenant_id: int, link_id: int, days: int | None = None) -> ShareLink:
    link = ShareLink.query.filter_by(id=link_id, tenant_id=tenant_id).first()
    if not link:
        raise LookupError('Share link not found')
    if link.revoked_at:
        raise ValueError('A revoked link cannot be extended; generate a new one')
    link.expires_at = ShareLink.default_expiry(days)
    db.session.commit()
    return link


# ------------------------------------------------------------------ #
#  Visualiser (customer preview) links
# ------------------------------------------------------------------ #

def create_visualiser_link(
    tenant_id: int,
    quotation_id: int,
    created_by: int | None = None,
    ttl_days: int | None = None,
    force_new: bool = False,
) -> ShareLink:
    """Link to the read-only rendered preview of a quotation.

    The customer can only view, approve and comment on it. Reuses the active
    link unless force_new is set (which revokes the previous one).
    """
    from ...models.quotation import Quotation, QuotationStatus

    q = Quotation.query.filter_by(id=quotation_id, tenant_id=tenant_id).first()
    if not q:
        raise LookupError('Quotation not found')
    if q.status in QuotationStatus.TERMINAL or q.status == QuotationStatus.EXPIRED:
        raise ValueError('This quotation is closed; a preview link cannot be created.')
    if not q.line_items:
        raise ValueError('Add items to the quotation before sharing a preview.')

    return get_or_create_link(
        tenant_id=tenant_id,
        resource_type=ShareLinkType.VISUALISER,
        resource_id=quotation_id,
        created_by=created_by,
        ttl_days=ttl_days,
        force_new=force_new,
    )


def get_active_visualiser_by_token(token: str):
    """Active visualiser or master-quote link for the token, or None for any other type."""
    link = get_active_by_token(token)
    if not link or link.resource_type not in (
        ShareLinkType.VISUALISER, ShareLinkType.MASTER_QUOTE
    ):
        return None
    return link


def get_visualiser_link(tenant_id: int, quotation_id: int):
    """Latest visualiser link for a quotation (any state), for status display."""
    return get_latest(tenant_id, ShareLinkType.VISUALISER, quotation_id)


# ------------------------------------------------------------------ #
#  Master Quotation (combined customer page) links
# ------------------------------------------------------------------ #

def create_master_link(
    tenant_id: int,
    quotation_id: int,
    created_by: int | None = None,
    ttl_days: int | None = None,
    force_new: bool = False,
) -> ShareLink:
    """One customer link carrying visual preview, quotation, payment and
    progress for a quotation version.

    Stays valid after acceptance so the customer can follow payment and
    progress; only a draft or lost quotation cannot be shared.
    """
    from ...models.quotation import Quotation, QuotationStatus

    q = Quotation.query.filter_by(id=quotation_id, tenant_id=tenant_id).first()
    if not q:
        raise LookupError('Quotation not found')
    if q.status in (QuotationStatus.DRAFT, QuotationStatus.PENDING_DISCOUNT_APPROVAL):
        raise ValueError('Send the quotation to the customer first, then copy the link.')
    if q.status in (QuotationStatus.LOST, QuotationStatus.EXPIRED):
        raise ValueError('This quotation is closed; a link cannot be created.')
    if not q.line_items:
        raise ValueError('Add items to the quotation before sharing it.')

    return get_or_create_link(
        tenant_id=tenant_id,
        resource_type=ShareLinkType.MASTER_QUOTE,
        resource_id=quotation_id,
        created_by=created_by,
        ttl_days=ttl_days,
        force_new=force_new,
    )


def get_master_link(tenant_id: int, quotation_id: int):
    """Latest master link for a quotation (any state), for status display."""
    return get_latest(tenant_id, ShareLinkType.MASTER_QUOTE, quotation_id)
