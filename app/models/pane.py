from ..extensions import db


class Pane(db.Model):
    __tablename__ = 'panes'

    id          = db.Column(db.Integer, primary_key=True)
    window_id   = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=False, index=True)
    cell_key    = db.Column(db.String(40), nullable=False)   # matches JS model cell id
    x_norm      = db.Column(db.Float, nullable=False, default=0.0)  # normalised 0–1 grid
    y_norm      = db.Column(db.Float, nullable=False, default=0.0)
    w_norm      = db.Column(db.Float, nullable=False, default=1.0)
    h_norm      = db.Column(db.Float, nullable=False, default=1.0)
    opener_type = db.Column(db.String(80), nullable=False, default='Fixed light')
    glazing_type= db.Column(db.String(80), nullable=False, default='Double, Low-E')
    infill      = db.Column(db.String(10), nullable=False, default='glass')  # glass | panel

    def to_dict(self) -> dict:
        """Serialise to the shape the Three.js model.cells array expects."""
        return {
            'id':      self.cell_key,
            'x':       self.x_norm,
            'y':       self.y_norm,
            'w':       self.w_norm,
            'h':       self.h_norm,
            'opener':  self.opener_type,
            'glazing': self.glazing_type,
            'infill':  self.infill,
        }

    def __repr__(self):
        return f'<Pane {self.cell_key} {self.opener_type}>'