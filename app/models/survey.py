import json
from datetime import datetime
from ..extensions import db


class SurveyStatus:
    SCHEDULED    = 'SURVEY-SCHEDULED'
    COMPLETED    = 'SURVEY-COMPLETED'
    ISSUES_FOUND = 'SURVEY-ISSUES_FOUND'
    RESCHEDULED  = 'SURVEY-RESCHEDULED'

    ALL = [SCHEDULED, COMPLETED, ISSUES_FOUND, RESCHEDULED]
    LABELS = {
        SCHEDULED:    'Scheduled',
        COMPLETED:    'Completed',
        ISSUES_FOUND: 'Issues Found',
        RESCHEDULED:  'Rescheduled',
    }


class Survey(db.Model):
    __tablename__ = 'surveys'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    lead_id     = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    project_id  = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    presel_id   = db.Column(db.Integer, db.ForeignKey('preliminary_selections.id'), nullable=True, index=True)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    scheduled_date = db.Column(db.Date, nullable=True)
    completed_date = db.Column(db.Date, nullable=True)
    surveyor_name  = db.Column(db.String(200), nullable=True)
    notes          = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), default=SurveyStatus.SCHEDULED, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    lead    = db.relationship('Lead', backref=db.backref('surveys', lazy='dynamic'))
    project = db.relationship('Project', backref=db.backref('surveys', lazy='dynamic'))
    presel  = db.relationship('PreliminarySelection', backref=db.backref('surveys', lazy='dynamic'))

    openings = db.relationship(
        'SurveyOpening', backref='survey', lazy='dynamic',
        cascade='all, delete-orphan'
    )

    @property
    def status_label(self) -> str:
        return SurveyStatus.LABELS.get(self.status, self.status)

    @property
    def opening_count(self) -> int:
        return self.openings.count()

    @property
    def has_blocking_issues(self) -> bool:
        return self.openings.filter(SurveyOpening.site_issue_flags.isnot(None)) \
            .filter(SurveyOpening.site_issue_flags != '').count() > 0

    def to_dict(self) -> dict:
        return {
            'id':              self.id,
            'tenant_id':       self.tenant_id,
            'lead_id':         self.lead_id,
            'project_id':      self.project_id,
            'presel_id':       self.presel_id,
            'created_by':      self.created_by,
            'scheduled_date':  self.scheduled_date.isoformat() if self.scheduled_date else None,
            'completed_date':  self.completed_date.isoformat() if self.completed_date else None,
            'surveyor_name':   self.surveyor_name,
            'notes':           self.notes,
            'status':          self.status,
            'status_label':    self.status_label,
            'opening_count':   self.opening_count,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
            'updated_at':      self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Survey lead={self.lead_id} project={self.project_id} {self.status}>'


class SurveyOpening(db.Model):
    __tablename__ = 'survey_openings'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    survey_id  = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=False, index=True)

    opening_label = db.Column(db.String(100), nullable=False)   # e.g. L16, D19
    location_room = db.Column(db.String(200), nullable=True)

    measured_width_mm  = db.Column(db.Integer, nullable=True)
    measured_height_mm = db.Column(db.Integer, nullable=True)
    wall_thickness_mm  = db.Column(db.Integer, nullable=True)
    sill_height_mm     = db.Column(db.Integer, nullable=True)

    site_condition_notes = db.Column(db.Text, nullable=True)
    photo_refs           = db.Column(db.Text, nullable=True)   # JSON list of uploaded file paths
    site_issue_flags     = db.Column(db.Text, nullable=True)   # JSON list, e.g. ["out-of-square","damp"]

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    @property
    def photo_ref_list(self) -> list:
        if not self.photo_refs:
            return []
        try:
            return json.loads(self.photo_refs)
        except (ValueError, TypeError):
            return []

    @property
    def site_issue_flag_list(self) -> list:
        if not self.site_issue_flags:
            return []
        try:
            return json.loads(self.site_issue_flags)
        except (ValueError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            'id':                  self.id,
            'survey_id':           self.survey_id,
            'opening_label':       self.opening_label,
            'location_room':       self.location_room,
            'measured_width_mm':   self.measured_width_mm,
            'measured_height_mm':  self.measured_height_mm,
            'wall_thickness_mm':   self.wall_thickness_mm,
            'sill_height_mm':      self.sill_height_mm,
            'site_condition_notes': self.site_condition_notes,
            'photo_refs':          self.photo_ref_list,
            'site_issue_flags':    self.site_issue_flag_list,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<SurveyOpening {self.opening_label} survey={self.survey_id}>'
