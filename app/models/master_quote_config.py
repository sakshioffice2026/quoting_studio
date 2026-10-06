import json
from datetime import datetime

from ..extensions import db


class MasterQuoteConfig(db.Model):
    """
    Which sections the Master Quotation shows.

    quotation_id NULL  -> the tenant-wide default template.
    quotation_id set   -> a per-quotation override.
    """
    __tablename__ = 'master_quote_configs'
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'quotation_id', name='uq_master_cfg_tenant_quote'),
    )

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    quotation_id  = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=True, index=True)

    sections_json = db.Column(db.Text, nullable=False, default='{}')

    updated_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def sections(self) -> dict:
        try:
            data = json.loads(self.sections_json or '{}')
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def __repr__(self):
        return f'<MasterQuoteConfig tenant={self.tenant_id} quotation={self.quotation_id}>'
