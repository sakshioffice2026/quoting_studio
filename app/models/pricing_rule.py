from ..extensions import db


class PricingRule(db.Model):
    """Per-material frame + glass + fitting rates, one row per tenant+material."""
    __tablename__ = 'pricing_rules'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    material             = db.Column(db.String(50), nullable=False)
    frame_cost_per_metre = db.Column(db.Numeric(8, 2), nullable=False, default=3.20)
    glass_cost_per_m2    = db.Column(db.Numeric(8, 2), nullable=False, default=95.00)
    fitting_fixed        = db.Column(db.Numeric(8, 2), nullable=False, default=140.00)
    is_active            = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'material', name='uq_pricing_tenant_material'),
    )

    def __repr__(self):
        return f'<PricingRule {self.material} tenant={self.tenant_id}>'


class OpenerPricingRule(db.Model):
    """Hardware cost per opener type, one row per tenant+opener."""
    __tablename__ = 'opener_pricing_rules'

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    opener_type   = db.Column(db.String(80), nullable=False)
    hardware_cost = db.Column(db.Numeric(8, 2), nullable=False, default=0.00)
    is_active     = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'opener_type', name='uq_opener_tenant_type'),
    )

    def __repr__(self):
        return f'<OpenerPricingRule {self.opener_type}>'


class GlazingPricingRule(db.Model):
    """Cost multiplier on glass base price per glazing type."""
    __tablename__ = 'glazing_pricing_rules'

    id               = db.Column(db.Integer, primary_key=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    glazing_type     = db.Column(db.String(80), nullable=False)
    cost_multiplier  = db.Column(db.Float, nullable=False, default=0.0)
    is_active        = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'glazing_type', name='uq_glazing_tenant_type'),
    )

    def __repr__(self):
        return f'<GlazingPricingRule {self.glazing_type}>'
