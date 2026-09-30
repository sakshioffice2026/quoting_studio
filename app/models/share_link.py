import secrets
from datetime import datetime

from ..extensions import db


class ShareResource:
    QUOTATION       = 'quotation'
    DESIGN_APPROVAL = 'design_approval'

    ALL = (QUOTATION, DESIGN_APPROVAL)


class ShareLink(db.Model):
    """Tokenised public link a customer can open without logging in.
    One active link per (tenant, resource_type, resource_id)."""

    __tablename__ = 'share_links'

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    resource_type = db.Column(db.String(30), nullable=False)
    resource_id   = db.Column(db.Integer, nullable=False)

    token         = db.Column(db.String(64), unique=True, nullable=False, index=True)

    created_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at    = db.Column(db.DateTime, nullable=True)
    revoked_at    = db.Column(db.DateTime, nullable=True)

    first_viewed_at = db.Column(db.DateTime, nullable=True)
    last_viewed_at  = db.Column(db.DateTime, nullable=True)
    view_count      = db.Column(db.Integer, nullable=False, default=0)
    responded_at    = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_share_links_resource', 'tenant_id', 'resource_type', 'resource_id'),
    )

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired

    @property
    def state(self) -> str:
        if self.is_revoked:
            return 'Revoked'
        if self.is_expired:
            return 'Expired'
        if self.responded_at:
            return 'Responded'
        if self.view_count:
            return 'Viewed'
        return 'Not opened'
