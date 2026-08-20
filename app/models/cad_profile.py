"""
CadProfile — window/door frame profile library.
Each profile has a code (HF-90), category, real dimensions, and optional
DXF geometry (LWPOLYLINE vertices) for accurate cross-section rendering.
"""
from datetime import datetime
from ..extensions import db


class CadProfile(db.Model):
    __tablename__ = 'cad_profiles'

    id               = db.Column(db.Integer, primary_key=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'),
                                  nullable=False, index=True)

    # Library identity
    code             = db.Column(db.String(30),  nullable=False, default='')
    # e.g. HF-90, SF-165, GB-58
    name             = db.Column(db.String(120), nullable=False)
    category         = db.Column(db.String(40),  nullable=False, default='Frame')
    # Frame | Sash | Sill | GlazingBead | Mullion | Transom | Hardware
    drawing_ref      = db.Column(db.String(80),  nullable=True)
    material         = db.Column(db.String(50),  nullable=False, default='Aluminium')
    is_builtin       = db.Column(db.Boolean, default=True)

    # Semantic member role — drives the 3D frame assembly (which profile is swept
    # along which member). Distinct from the looser `category` label above.
    #   outer_frame | head | cill | jamb | sash | mullion | transom
    #   | glazing_bead | threshold | coupler
    role             = db.Column(db.String(30), nullable=True, index=True)
    # When true, this profile is the default for its role in the assembly.
    is_role_default  = db.Column(db.Boolean, default=False)

    # Profile dimensions (mm)
    bar_width_mm     = db.Column(db.Float, nullable=False, default=40.0)
    wall_thickness_mm= db.Column(db.Float, nullable=False, default=4.0)
    depth_mm         = db.Column(db.Float, nullable=False, default=52.0)
    rebate_w_mm      = db.Column(db.Float, nullable=False, default=0.0)
    rebate_d_mm      = db.Column(db.Float, nullable=False, default=0.0)
    glass_rebate_mm  = db.Column(db.Float, nullable=False, default=20.0)
    weather_seal_mm  = db.Column(db.Float, nullable=False, default=2.0)

    # DXF geometry — JSON array of [x,y] vertex pairs (LWPOLYLINE normalized to mm)
    geometry_json    = db.Column(db.Text, nullable=True)
    # SVG path string pre-computed from geometry_json for fast rendering (200×200 viewBox)
    svg_path         = db.Column(db.Text, nullable=True)
    vertex_count     = db.Column(db.Integer, nullable=True)
    source_file      = db.Column(db.String(500), nullable=True)

    is_active        = db.Column(db.Boolean, default=True)
    is_default       = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CadProfile {self.code} {self.name}>'

    @property
    def has_geometry(self):
        return bool(self.geometry_json)

    def to_dict(self) -> dict:
        return {
            'id':            self.id,
            'code':          self.code,
            'name':          self.name,
            'category':      self.category,
            'role':          self.role,
            'is_role_default': self.is_role_default,
            'drawing_ref':   self.drawing_ref,
            'material':      self.material,
            'bar_width_mm':  self.bar_width_mm,
            'depth_mm':      self.depth_mm,
            'rebate_w_mm':   self.rebate_w_mm,
            'rebate_d_mm':   self.rebate_d_mm,
            'glass_rebate':  self.glass_rebate_mm,
            'has_geometry':  self.has_geometry,
            'svg_path':      self.svg_path,
            'vertex_count':  self.vertex_count,
        }