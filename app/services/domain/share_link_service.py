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
