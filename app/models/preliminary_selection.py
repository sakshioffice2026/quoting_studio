from datetime import datetime
from ..extensions import db


class PreselStatus:
    IN_PROGRESS = 'PRESEL-IN_PROGRESS'
    SHORTLISTED = 'PRESEL-SHORTLISTED'
    ON_HOLD     = 'PRESEL-ON_HOLD'
    DROPPED     = 'PRESEL-DROPPED'

    ALL = [IN_PROGRESS, SHORTLISTED, ON_HOLD, DROPPED]
    LABELS = {
        IN_PROGRESS: 'In Progress',
        SHORTLISTED: 'Shortlisted',
        ON_HOLD:     'On Hold',
        DROPPED:     'Dropped',
    }


class PreliminarySelection(db.Model):
    __tablename__ = 'preliminary_selections'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    lead_id    = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    shortlisted_ranges    = db.Column(db.Text, nullable=True)     # product lines / finish families
    rough_opening_doors   = db.Column(db.Integer, nullable=True)
    rough_opening_windows = db.Column(db.Integer, nullable=True)
    indicative_price_min  = db.Column(db.Numeric(12, 2), nullable=True)
    indicative_price_max  = db.Column(db.Numeric(12, 2), nullable=True)
    survey_required       = db.Column(db.Boolean, nullable=False, default=True)
    notes                 = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), default=PreselStatus.IN_PROGRESS, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    lead    = db.relationship('Lead', backref=db.backref('preliminary_selections', lazy='dynamic'))
    project = db.relationship('Project', backref=db.backref('preliminary_selections', lazy='dynamic'))

    @property
    def status_label(self) -> str:
        return PreselStatus.LABELS.get(self.status, self.status)

    @property
    def rough_opening_count(self) -> int:
        return (self.rough_opening_doors or 0) + (self.rough_opening_windows or 0)

    def to_dict(self) -> dict:
        return {
            'id':                    self.id,
            'tenant_id':             self.tenant_id,
            'lead_id':               self.lead_id,
            'project_id':            self.project_id,
            'created_by':            self.created_by,
            'shortlisted_ranges':    self.shortlisted_ranges,
            'rough_opening_doors':   self.rough_opening_doors,
            'rough_opening_windows': self.rough_opening_windows,
            'rough_opening_count':   self.rough_opening_count,
            'indicative_price_min':  float(self.indicative_price_min) if self.indicative_price_min is not None else None,
            'indicative_price_max':  float(self.indicative_price_max) if self.indicative_price_max is not None else None,
            'survey_required':       self.survey_required,
            'notes':                 self.notes,
            'status':                self.status,
            'status_label':          self.status_label,
            'created_at':            self.created_at.isoformat() if self.created_at else None,
            'updated_at':            self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<PreliminarySelection lead={self.lead_id} project={self.project_id} {self.status}>'
