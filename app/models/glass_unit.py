"""
GlassUnit — named glazing unit library.
Stores real build-up specs (4/16/4), U-value, and description.
Used in the Glass tab dropdown and feeds Building Regs compliance on quotes.
"""
from datetime import datetime
from ..extensions import db


class GlassUnit(db.Model):
    __tablename__ = 'glass_units'

    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenants.id'),
                              nullable=False, index=True)

    code         = db.Column(db.String(30),  nullable=False, default='')
    # e.g. DG-24, TG-40, SG-4
    name         = db.Column(db.String(120), nullable=False)
    # e.g. "Double Glazed 4/16/4 Low-E"
    build_up     = db.Column(db.String(60),  nullable=False, default='')
    # e.g. "4/16/4"
    thickness_mm = db.Column(db.Float, nullable=False, default=24.0)
    u_value      = db.Column(db.Float, nullable=True)
    # W/m²K — shown as tooltip in editor and on quotes
    g_value      = db.Column(db.Float, nullable=True)
    # Solar factor (optional)
    price_per_m2 = db.Column(db.Numeric(10, 2), nullable=True)
    # £/m² supply rate for this glazing spec (UK trade convention)
    description  = db.Column(db.String(300), nullable=True)
    is_builtin   = db.Column(db.Boolean, default=True)
    is_active    = db.Column(db.Boolean, default=True)
    sort_order   = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<GlassUnit {self.code} {self.name}>'

    @property
    def display_name(self):
        """Short name for dropdown: "DG-24 — Double Glazed 4/16/4 (24mm)"."""
        return f'{self.code} — {self.name} ({self.thickness_mm:.0f}mm)'

    @property
    def tooltip(self):
        parts = []
        if self.build_up:
            parts.append(f'Build-up: {self.build_up}')
        if self.u_value is not None:
            parts.append(f'U-value: {self.u_value} W/m²K')
        if self.g_value is not None:
            parts.append(f'g-value: {self.g_value}')
        return ' | '.join(parts)

    def to_dict(self):
        return {
            'id':           self.id,
            'code':         self.code,
            'name':         self.name,
            'build_up':     self.build_up,
            'thickness_mm': self.thickness_mm,
            'u_value':      self.u_value,
            'g_value':      self.g_value,
            'price_per_m2': float(self.price_per_m2) if self.price_per_m2 is not None else None,
            'description':  self.description,
            'display_name': self.display_name,
            'tooltip':      self.tooltip,
        }