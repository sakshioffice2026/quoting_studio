from datetime import datetime
from ..extensions import db


class Customer(db.Model):
    """Deduplicated customer identity. Leads merge into a Customer by
    phone/email match; a Customer may have multiple Leads/Projects over time."""

    __tablename__ = 'customers'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name       = db.Column(db.String(200), nullable=False)
    phone      = db.Column(db.String(30), nullable=True, index=True)
    email      = db.Column(db.String(200), nullable=True, index=True)
    city       = db.Column(db.String(120), nullable=True)
    address    = db.Column(db.String(500), nullable=True)
    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    leads = db.relationship('Lead', backref='customer', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_customers_tenant_phone', 'tenant_id', 'phone'),
        db.Index('ix_customers_tenant_email', 'tenant_id', 'email'),
    )

    def to_dict(self) -> dict:
        return {
            'id':         self.id,
            'tenant_id':  self.tenant_id,
            'name':       self.name,
            'phone':      self.phone,
            'email':      self.email,
            'city':       self.city,
            'address':    self.address,
            'notes':      self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Customer {self.name}>'
