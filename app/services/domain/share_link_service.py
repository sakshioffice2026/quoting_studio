from datetime import datetime, timedelta

from ...extensions import db
from ...models.design_approval import DesignApproval
from ...models.quotation import Quotation
from ...models.share_link import ShareLink, ShareResource

DEFAULT_EXPIRY_DAYS = 30


def _resource_exists(tenant_id: int, resource_type: str, resource_id: int) -> bool:
    if resource_type == ShareResource.QUOTATION:
        model = Quotation
    elif resource_type == ShareResource.DESIGN_APPROVAL:
        model = DesignApproval
    else:
        return False
    return model.query.filter_by(id=resource_id, tenant_id=tenant_id).first() is not None


def get_active_link(tenant_id: int, resource_type: str, resource_id: int) -> ShareLink | None:
    links = (ShareLink.query
             .filter_by(tenant_id=tenant_id, resource_type=resource_type, resource_id=resource_id)
             .filter(ShareLink.revoked_at.is_(None))
             .order_by(ShareLink.created_at.desc())
             .all())
    for link in links:
        if not link.is_expired:
            return link
    return None


def get_or_create(tenant_id: int, resource_type: str, resource_id: int,
                  user_id: int | None, expiry_days: int | None = DEFAULT_EXPIRY_DAYS) -> ShareLink:
    if resource_type not in ShareResource.ALL:
        raise ValueError('Unsupported resource type')
    if not _resource_exists(tenant_id, resource_type, resource_id):
        raise LookupError('Record not found')

    existing = get_active_link(tenant_id, resource_type, resource_id)
    if existing:
        return existing

    link = ShareLink(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        token=ShareLink.new_token(),
        created_by=user_id,
        created_at=datetime.utcnow(),
        expires_at=(datetime.utcnow() + timedelta(days=expiry_days)) if expiry_days else None,
    )
    db.session.add(link)
    db.session.commit()
    return link


def revoke(tenant_id: int, resource_type: str, resource_id: int) -> int:
    now = datetime.utcnow()
    links = (ShareLink.query
             .filter_by(tenant_id=tenant_id, resource_type=resource_type, resource_id=resource_id)
             .filter(ShareLink.revoked_at.is_(None))
             .all())
    for link in links:
        link.revoked_at = now
    db.session.commit()
    return len(links)


def regenerate(tenant_id: int, resource_type: str, resource_id: int,
               user_id: int | None, expiry_days: int | None = DEFAULT_EXPIRY_DAYS) -> ShareLink:
    revoke(tenant_id, resource_type, resource_id)
    return get_or_create(tenant_id, resource_type, resource_id, user_id, expiry_days)


def find_by_token(token: str) -> ShareLink | None:
    if not token or len(token) > 64:
        return None
    return ShareLink.query.filter_by(token=token).first()


def mark_viewed(link: ShareLink) -> None:
    now = datetime.utcnow()
    if not link.first_viewed_at:
        link.first_viewed_at = now
    link.last_viewed_at = now
    link.view_count = (link.view_count or 0) + 1
    db.session.commit()


def mark_responded(link: ShareLink) -> None:
    link.responded_at = datetime.utcnow()
    db.session.commit()


def load_resource(link: ShareLink):
    if link.resource_type == ShareResource.QUOTATION:
        return Quotation.query.filter_by(id=link.resource_id, tenant_id=link.tenant_id).first()
    if link.resource_type == ShareResource.DESIGN_APPROVAL:
        return DesignApproval.query.filter_by(id=link.resource_id, tenant_id=link.tenant_id).first()
    return None
