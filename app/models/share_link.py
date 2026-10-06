import secrets
from datetime import datetime, timedelta

from ..extensions import db


class ShareLinkType:
    QUOTATION       = 'QUOTATION'
    DESIGN_APPROVAL = 'DESIGN_APPROVAL'
    # Customer-facing visual preview of a quotation (rendered photo, approve /
    # comment only). resource_id = quotation id.
    VISUALISER      = 'VISUALISER'

    ALL = [QUOTATION, DESIGN_APPROVAL, VISUALISER]


# Backward-compatible alias (models/__init__.py imports ShareResource)
ShareResource = ShareLinkType


class ShareLink(db.Model):
    """Secure, expiring, revocable link a sales user sends to a customer.
    One row per generated link. The token is the only thing in the URL,
    so no internal ids are ever exposed to the customer."""

    __tablename__ = 'share_links'

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    resource_type = db.Column(db.String(30), nullable=False)
    resource_id   = db.Column(db.Integer, nullable=False)

    token         = db.Column(db.String(64), nullable=False, unique=True, index=True)

    created_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at    = db.Column(db.DateTime, nullable=False)
    revoked_at    = db.Column(db.DateTime, nullable=True)

    # tracking shown back to the sales user
    first_opened_at = db.Column(db.DateTime, nullable=True)
    last_opened_at  = db.Column(db.DateTime, nullable=True)
    open_count      = db.Column(db.Integer, nullable=False, default=0)
    responded_at    = db.Column(db.DateTime, nullable=True)
    response_action = db.Column(db.String(30), nullable=True)   # ACCEPTED / REJECTED / APPROVED / CHANGES_REQUESTED (visualiser: APPROVED / CHANGES_REQUESTED)

    __table_args__ = (
        db.Index('ix_share_links_resource', 'resource_type', 'resource_id'),
    )

    DEFAULT_TTL_DAYS = 14

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def default_expiry(days: int | None = None) -> datetime:
        return datetime.utcnow() + timedelta(days=days or ShareLink.DEFAULT_TTL_DAYS)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired

    @property
    def status_label(self) -> str:
        if self.is_revoked:
            return 'Revoked'
        if self.is_expired:
            return 'Expired'
        if self.responded_at:
            return 'Responded'
        if self.first_opened_at:
            return 'Opened'
        return 'Not opened'

    def to_dict(self) -> dict:
        return {
            'id':              self.id,
            'resource_type':   self.resource_type,
            'resource_id':     self.resource_id,
            'expires_at':      self.expires_at.isoformat() if self.expires_at else None,
            'first_opened_at': self.first_opened_at.isoformat() if self.first_opened_at else None,
            'last_opened_at':  self.last_opened_at.isoformat() if self.last_opened_at else None,
            'open_count':      self.open_count,
            'responded_at':    self.responded_at.isoformat() if self.responded_at else None,
            'response_action': self.response_action,
            'status_label':    self.status_label,
            'is_active':       self.is_active,
        }

    def __repr__(self):
        return f'<ShareLink {self.resource_type}:{self.resource_id} {self.status_label}>'
