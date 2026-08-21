from ..extensions import db

# RAL colour codes matching the 6 frame colour swatches
FRAME_COLOUR_RAL = {
    '#2B2F33': 'RAL 7016',  # Anthracite
    '#E8E4DA': 'RAL 9016',  # White
    '#7C8AA0': 'RAL 7015',  # Slate
    '#7c8aa0': 'RAL 7015',
    '#5C4733': 'RAL 8019',  # Bronze
    '#5c4733': 'RAL 8019',
    '#1B2430': 'RAL 5004',  # Midnight
    '#1b2430': 'RAL 5004',
    '#4A6741': 'RAL 6021',  # Sage
    '#4a6741': 'RAL 6021',
}


class Window(db.Model):
    __tablename__ = 'windows'

    id               = db.Column(db.Integer, primary_key=True)
    project_id       = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    label            = db.Column(db.String(200), nullable=False, default='Window')
    width_mm         = db.Column(db.Integer, nullable=False, default=1200)
    height_mm        = db.Column(db.Integer, nullable=False, default=1400)
    material         = db.Column(db.String(50), nullable=False, default='Aluminium')
    frame_colour_hex = db.Column(db.String(7), nullable=False, default='#2B2F33')
    frame_colour_name= db.Column(db.String(80), nullable=False, default='Anthracite')
    sequence_order   = db.Column(db.Integer, nullable=False, default=0)
    design_json      = db.Column(db.Text, nullable=True)
    # Optional: pin a specific ProfileSystem for this window/door.
    # NULL → frame_assembly falls back to role-default lookup.
    profile_system_id = db.Column(
        db.Integer, db.ForeignKey('profile_systems.id'),
        nullable=True, index=True)
    profile_system    = db.relationship('ProfileSystem',
                                        foreign_keys=[profile_system_id])

    # relationships
    panes = db.relationship(
        'Pane', backref='window', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    visualisations = db.relationship(
        'Visualisation', backref='window', lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # ------------------------------------------------------------------ #
    @property
    def ral_code(self) -> str:
        return FRAME_COLOUR_RAL.get(self.frame_colour_hex, '')

    @property
    def material_spec(self) -> str:
        """Returns e.g. 'Aluminium · Anthracite (RAL 7016)'"""
        ral = self.ral_code
        if ral:
            return f'{self.material} · {self.frame_colour_name} ({ral})'
        return f'{self.material} · {self.frame_colour_name}'

    def to_dict(self) -> dict:
        """Serialise the authoritative designer model.

        When design_json exists, cells are projected from it rather than from
        the legacy Pane relation, preventing API consumers from seeing two
        different geometries for the same window.
        """
        cells = [p.to_dict() for p in self.panes.all()]
        if self.design_json:
            try:
                from ..services.canonical_geometry import legacy_panes_from_design
                cells = legacy_panes_from_design(self)
            except Exception:
                # Do not hide a malformed design_json behind stale Pane rows.
                cells = []
        return {
            'id':             self.id,
            'label':          self.label,
            'width':          self.width_mm,
            'height':         self.height_mm,
            'material':       self.material,
            'frameColor':     self.frame_colour_hex,
            'frameColorName': self.frame_colour_name,
            'design_json':    self.design_json,
            'cells':          cells,
        }

    def __repr__(self):
        return f'<Window {self.label} {self.width_mm}x{self.height_mm}>'