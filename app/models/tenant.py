import re
from datetime import datetime
from ..extensions import db


class Tenant(db.Model):
    __tablename__ = 'tenants'

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    slug          = db.Column(db.String(80), unique=True, nullable=False, index=True)
    contact_email = db.Column(db.String(200), nullable=False)
    logo_path     = db.Column(db.String(500), nullable=True)
    brand_colour  = db.Column(db.String(7), default='#C97B3D')   # copper default
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # relationships
    users         = db.relationship('User',            backref='tenant', lazy='dynamic')
    projects      = db.relationship('Project',         backref='tenant', lazy='dynamic')
    pricing_rules = db.relationship('PricingRule',     backref='tenant', lazy='dynamic')
    opener_rules  = db.relationship('OpenerPricingRule',  backref='tenant', lazy='dynamic')
    glazing_rules = db.relationship('GlazingPricingRule', backref='tenant', lazy='dynamic')
    quotes        = db.relationship('Quote',           backref='tenant', lazy='dynamic')

    @staticmethod
    def generate_slug(name: str) -> str:
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        return slug.strip('-')

    def __repr__(self):
        return f'<Tenant {self.name}>'
