"""
ProductSeries and WindowStyle — the product catalog that drives the
drawing engine workflow: Add Product → Product Series → Window Style → Canvas.
"""
from datetime import datetime
from ..extensions import db


class ProductSeries(db.Model):
    __tablename__ = 'product_series'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name        = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(400))
    thumbnail   = db.Column(db.String(500))
    material    = db.Column(db.String(50), default='Aluminium')
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    styles = db.relationship('WindowStyle', backref='series',
                              lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description,
                'thumbnail': self.thumbnail, 'material': self.material,
                'style_count': self.styles.count()}


class WindowStyle(db.Model):
    __tablename__ = 'window_styles'

    id               = db.Column(db.Integer, primary_key=True)
    series_id        = db.Column(db.Integer, db.ForeignKey('product_series.id'),
                                  nullable=False, index=True)
    name             = db.Column(db.String(120), nullable=False)
    panels           = db.Column(db.Integer, default=1)      # initial pane count
    image            = db.Column(db.String(500))
    default_template = db.Column(db.Text)                     # JSON template
    sort_order       = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {'id': self.id, 'series_id': self.series_id, 'name': self.name,
                'panels': self.panels, 'image': self.image,
                'default_template': self.default_template}
