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
    brand_colour  = db.Column(db.String(7), default='#C97B3D')
    currency_code = db.Column(db.String(3), nullable=False, default='INR')
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    users         = db.relationship('User', backref='tenant', lazy='dynamic')
    projects      = db.relationship('Project', backref='tenant', lazy='dynamic')
    pricing_rules = db.relationship('PricingRule', backref='tenant', lazy='dynamic')
    opener_rules  = db.relationship('OpenerPricingRule', backref='tenant', lazy='dynamic')
    glazing_rules = db.relationship('GlazingPricingRule', backref='tenant', lazy='dynamic')
    quotations    = db.relationship('Quotation', backref='tenant', lazy='dynamic')

    CURRENCIES = {
        'INR': {'name': 'Indian Rupee', 'symbol': '₹', 'decimal_places': 2},
        'USD': {'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2},
        'EUR': {'name': 'Euro', 'symbol': '€', 'decimal_places': 2},
        'GBP': {'name': 'British Pound', 'symbol': '£', 'decimal_places': 2},
        'AED': {'name': 'UAE Dirham', 'symbol': 'د.إ', 'decimal_places': 2},
        'AUD': {'name': 'Australian Dollar', 'symbol': 'A$', 'decimal_places': 2},
        'CAD': {'name': 'Canadian Dollar', 'symbol': 'C$', 'decimal_places': 2},
        'SGD': {'name': 'Singapore Dollar', 'symbol': 'S$', 'decimal_places': 2},
    }

    @property
    def quotes(self):
        return self.quotations

    @property
    def currency(self):
        return self.CURRENCIES.get(
            self.currency_code,
            self.CURRENCIES['INR']
        )

    @property
    def currency_symbol(self):
        return self.currency['symbol']

    @property
    def currency_name(self):
        return self.currency['name']

    @staticmethod
    def generate_slug(name: str) -> str:
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        return slug.strip('-')

    def __repr__(self):
        return f'<Tenant {self.name}>'
