import json
from datetime import datetime

from ..extensions import db


GLASS_TINTS = {
    'clear':  '#DCEBF5',
    'grey':   '#8A97A3',
    'bronze': '#A88B6A',
    'blue':   '#8FB4D1',
    'green':  '#9CBFA8',
}


class VisualScene(db.Model):
    """One house photo per project, holding many window/door openings."""
    __tablename__ = 'visual_scenes'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'),
                                nullable=False, index=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('projects.id'),
                                nullable=False, index=True)
    quotation_id    = db.Column(db.Integer, db.ForeignKey('quotations.id'),
                                nullable=True, index=True)
    photo_path      = db.Column(db.String(500), nullable=True)
    photo_width     = db.Column(db.Integer, nullable=True)
    photo_height    = db.Column(db.Integer, nullable=True)
    rendered_path   = db.Column(db.String(500), nullable=True)
    version         = db.Column(db.Integer, nullable=False, default=1)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow,
                                onupdate=datetime.utcnow)

    openings = db.relationship(
        'VisualSceneOpening', backref='scene', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='VisualSceneOpening.z_index',
    )

    def to_dict(self) -> dict:
        return {
            'id':           self.id,
            'project_id':   self.project_id,
            'quotation_id': self.quotation_id,
            'photo_path':   self.photo_path,
            'photo_width':  self.photo_width,
            'photo_height': self.photo_height,
            'rendered_path': self.rendered_path,
            'version':      self.version,
            'openings':     [o.to_dict() for o in self.openings.all()],
        }

    def __repr__(self):
        return f'<VisualScene project={self.project_id}>'


class VisualSceneOpening(db.Model):
    """A window/door design placed on the scene photo with its 4 corners."""
    __tablename__ = 'visual_scene_openings'

    id            = db.Column(db.Integer, primary_key=True)
    scene_id      = db.Column(db.Integer, db.ForeignKey('visual_scenes.id'),
                              nullable=False, index=True)
    window_id     = db.Column(db.Integer, db.ForeignKey('windows.id'),
                              nullable=False, index=True)
    corners_json  = db.Column(db.Text, nullable=True)
    opacity       = db.Column(db.Float, nullable=False, default=0.92)
    brightness    = db.Column(db.Float, nullable=False, default=1.0)
    glass_tint    = db.Column(db.String(20), nullable=False, default='clear')
    z_index       = db.Column(db.Integer, nullable=False, default=0)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    window = db.relationship('Window', foreign_keys=[window_id])

    @property
    def corners(self) -> dict:
        if not self.corners_json:
            return {}
        try:
            data = json.loads(self.corners_json)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @corners.setter
    def corners(self, value: dict) -> None:
        self.corners_json = json.dumps(value or {})

    @property
    def tint_hex(self) -> str:
        return GLASS_TINTS.get(self.glass_tint, GLASS_TINTS['clear'])

    def to_dict(self) -> dict:
        return {
            'id':         self.id,
            'scene_id':   self.scene_id,
            'window_id':  self.window_id,
            'corners':    self.corners,
            'opacity':    self.opacity,
            'brightness': self.brightness,
            'glass_tint': self.glass_tint,
            'tint_hex':   self.tint_hex,
            'z_index':    self.z_index,
        }

    def __repr__(self):
        return f'<VisualSceneOpening scene={self.scene_id} window={self.window_id}>'
