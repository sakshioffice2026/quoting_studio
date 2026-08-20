from datetime import datetime
from ..extensions import db


class Visualisation(db.Model):
    __tablename__ = 'visualisations'

    id            = db.Column(db.Integer, primary_key=True)
    window_id     = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=False, index=True)
    photo_path    = db.Column(db.String(500), nullable=True)
    corner_tl_x   = db.Column(db.Float, nullable=True)
    corner_tl_y   = db.Column(db.Float, nullable=True)
    corner_tr_x   = db.Column(db.Float, nullable=True)
    corner_tr_y   = db.Column(db.Float, nullable=True)
    corner_bl_x   = db.Column(db.Float, nullable=True)
    corner_bl_y   = db.Column(db.Float, nullable=True)
    corner_br_x   = db.Column(db.Float, nullable=True)
    corner_br_y   = db.Column(db.Float, nullable=True)
    opacity       = db.Column(db.Float, default=0.92)
    brightness    = db.Column(db.Float, default=1.0)
    rendered_path = db.Column(db.String(500), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def corners(self) -> dict:
        return {
            'tl': (self.corner_tl_x, self.corner_tl_y),
            'tr': (self.corner_tr_x, self.corner_tr_y),
            'bl': (self.corner_bl_x, self.corner_bl_y),
            'br': (self.corner_br_x, self.corner_br_y),
        }

    def to_dict(self) -> dict:
        return {
            'id':         self.id,
            'photo_path': self.photo_path,
            'corners':    self.corners,
            'opacity':    self.opacity,
            'brightness': self.brightness,
        }

    def __repr__(self):
        return f'<Visualisation window={self.window_id}>'
