from datetime import datetime
from ..extensions import db


class TemplateResponse(db.Model):
    __tablename__ = 'template_responses'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    lead_id         = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    project_type_id = db.Column(db.Integer, db.ForeignKey('project_types.id'), nullable=True)

    answers       = db.Column(db.JSON, nullable=True)
    is_submitted  = db.Column(db.Boolean, nullable=False, default=False)
    submitted_at  = db.Column(db.DateTime, nullable=True)

    site_type        = db.Column(db.String(30), nullable=True)
    project_type_ids = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    lead         = db.relationship('Lead', backref=db.backref('template_responses', lazy='dynamic'))
    project_type = db.relationship('ProjectType')

    @property
    def project_types(self):
        """All selected categories (Windows, Doors, ...) for this response."""
        from .project_type import ProjectType
        ids = self.project_type_ids or ([self.project_type_id] if self.project_type_id else [])
        if not ids:
            return []
        return ProjectType.query.filter(ProjectType.id.in_(ids)).all()

    def get_answer(self, question_key, default=None):
        if not self.answers:
            return default
        return self.answers.get(question_key, default)

    def set_answer(self, question_key, value):
        data = dict(self.answers or {})
        data[question_key] = value
        self.answers = data

    def to_dict(self) -> dict:
        return {
            'id':               self.id,
            'tenant_id':        self.tenant_id,
            'lead_id':          self.lead_id,
            'project_type_id':  self.project_type_id,
            'project_type_ids': self.project_type_ids,
            'site_type':        self.site_type,
            'answers':          self.answers,
            'is_submitted':     self.is_submitted,
            'submitted_at':     self.submitted_at.isoformat() if self.submitted_at else None,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
            'updated_at':       self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<TemplateResponse lead={self.lead_id} submitted={self.is_submitted}>'
