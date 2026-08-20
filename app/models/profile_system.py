"""
app/models/profile_system.py

A ProfileSystem groups individual CadProfile cross-sections into a named
set that covers every frame member role for both windows and doors.
One system maps to one aluminium (or timber/PVCu) series catalogue.

Slot layout
-----------
Outer frame (shared window + door):
  head_id           top outer-frame member
  cill_id           bottom outer-frame member (window)
  jamb_id           left / right outer-frame members

Door-specific outer frame:
  threshold_id      bottom member replacing cill for doors
  door_leaf_id      the door panel/sash profile (large solid or rebated)
  meeting_stile_id  interlocking vertical where two door leaves meet

Internal dividers (window + door):
  mullion_id        vertical internal divider
  transom_id        horizontal internal divider

Sash (opening window leaf):
  sash_top_id       top rail of sash
  sash_bottom_id    bottom rail of sash
  sash_side_id      stiles (left / right) of sash

Glazing:
  glazing_bead_id   bead retaining the IGU

Geometry rules (stored, used by frame_assembly + 3D builder):
  frame_corner_joint   'mitre_45' | 'butt'  (outer frame corners)
  sash_corner_joint    'mitre_45' | 'butt'  (sash corners)
  internal_joint       'butt'               (mullion / transom)
  sash_clearance_mm    operational gap between sash and outer frame (default 2)
"""
from __future__ import annotations
from ..extensions import db


class ProfileSystem(db.Model):
    __tablename__ = 'profile_systems'

    id        = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'),
                          nullable=False, index=True)
    name      = db.Column(db.String(120), nullable=False)
    material  = db.Column(db.String(50),  nullable=False, default='Aluminium')
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_active  = db.Column(db.Boolean, default=True,  nullable=False)
    notes     = db.Column(db.Text, nullable=True)

    # ── Outer frame slots ────────────────────────────────────────────
    head_id      = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    cill_id      = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    jamb_id      = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)

    # ── Door-specific ────────────────────────────────────────────────
    threshold_id     = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    door_leaf_id     = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    meeting_stile_id = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)

    # ── Internal dividers ────────────────────────────────────────────
    mullion_id  = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    transom_id  = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)

    # ── Sash (opening leaf) ──────────────────────────────────────────
    sash_top_id    = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    sash_bottom_id = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)
    sash_side_id   = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)

    # ── Glazing ──────────────────────────────────────────────────────
    glazing_bead_id = db.Column(db.Integer, db.ForeignKey('cad_profiles.id'), nullable=True)

    # ── Joint + geometry rules ────────────────────────────────────────
    frame_corner_joint = db.Column(db.String(20), default='mitre_45', nullable=False)
    sash_corner_joint  = db.Column(db.String(20), default='mitre_45', nullable=False)
    internal_joint     = db.Column(db.String(20), default='butt',     nullable=False)
    sash_clearance_mm  = db.Column(db.Float, default=2.0, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────
    head            = db.relationship('CadProfile', foreign_keys=[head_id])
    cill            = db.relationship('CadProfile', foreign_keys=[cill_id])
    jamb            = db.relationship('CadProfile', foreign_keys=[jamb_id])
    threshold       = db.relationship('CadProfile', foreign_keys=[threshold_id])
    door_leaf       = db.relationship('CadProfile', foreign_keys=[door_leaf_id])
    meeting_stile   = db.relationship('CadProfile', foreign_keys=[meeting_stile_id])
    mullion         = db.relationship('CadProfile', foreign_keys=[mullion_id])
    transom         = db.relationship('CadProfile', foreign_keys=[transom_id])
    sash_top        = db.relationship('CadProfile', foreign_keys=[sash_top_id])
    sash_bottom     = db.relationship('CadProfile', foreign_keys=[sash_bottom_id])
    sash_side       = db.relationship('CadProfile', foreign_keys=[sash_side_id])
    glazing_bead    = db.relationship('CadProfile', foreign_keys=[glazing_bead_id])

    # ── Slot name → relationship name map ────────────────────────────
    SLOTS = {
        # window + door
        'head':         'head',
        'cill':         'cill',
        'jamb':         'jamb',
        'mullion':      'mullion',
        'transom':      'transom',
        'sash_top':     'sash_top',
        'sash_bottom':  'sash_bottom',
        'sash_side':    'sash_side',
        'glazing_bead': 'glazing_bead',
        # door only
        'threshold':      'threshold',
        'door_leaf':      'door_leaf',
        'meeting_stile':  'meeting_stile',
    }

    # Slots that apply to a specific unit type
    WINDOW_SLOTS = ['head','cill','jamb','mullion','transom',
                    'sash_top','sash_bottom','sash_side','glazing_bead']
    DOOR_SLOTS   = ['head','threshold','jamb','mullion','transom',
                    'door_leaf','meeting_stile','sash_top','sash_bottom',
                    'sash_side','glazing_bead']

    def get_profile(self, slot: str):
        """Return the CadProfile for a given slot name, or None."""
        rel = self.SLOTS.get(slot)
        return getattr(self, rel, None) if rel else None

    def to_profile_set(self, unit_type: str = 'window'):
        """
        Convert this system into a frame_assembly.ProfileSet so the
        existing assembly code works without changes.

        For doors, 'cill' slot falls back to 'threshold'.
        For windows, 'sash_top/bottom/side' fall back to 'sash' role.
        """
        import json as _json
        by_role: dict = {}

        def _p(slot):
            prof = self.get_profile(slot)
            if not prof:
                return None
            loops = None
            if prof.geometry_json:
                try:
                    loops = _json.loads(prof.geometry_json)
                except Exception:
                    loops = None
            return {
                'code':         prof.code or prof.name,
                'bar':          float(prof.bar_width_mm),
                'depth':        float(prof.depth_mm),
                'glass_rebate': float(prof.glass_rebate_mm or 20.0),
                'loops':        loops,
            }

        slots_to_roles = {
            'head':          'head',
            'cill':          'cill',
            'threshold':     'threshold',
            'jamb':          'jamb',
            'mullion':       'mullion',
            'transom':       'transom',
            'sash_top':      'sash',       # sash rail top → 'sash' role
            'sash_bottom':   'sash',       # merged into sash role for now
            'sash_side':     'sash',
            'door_leaf':     'sash',       # door leaf treated as sash
            'meeting_stile': 'mullion',    # meeting stile acts like mullion
            'glazing_bead':  'glazing_bead',
        }

        for slot, role in slots_to_roles.items():
            d = _p(slot)
            if d and role not in by_role:
                by_role[role] = d

        # Door: cill role must resolve to threshold
        if unit_type == 'door' and 'threshold' in by_role and 'cill' not in by_role:
            by_role['cill'] = by_role['threshold']

        return by_role, float(self.sash_clearance_mm)

    def to_dict(self) -> dict:
        return {
            'id':       self.id,
            'name':     self.name,
            'material': self.material,
            'is_default': self.is_default,
            'is_active':  self.is_active,
            'notes':    self.notes or '',
            'frame_corner_joint': self.frame_corner_joint,
            'sash_corner_joint':  self.sash_corner_joint,
            'internal_joint':     self.internal_joint,
            'sash_clearance_mm':  self.sash_clearance_mm,
            'slots': {
                slot: (getattr(self, rel).code
                       if getattr(self, rel) else None)
                for slot, rel in self.SLOTS.items()
            },
        }
