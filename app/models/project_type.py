from datetime import datetime
from ..extensions import db


class ProjectType(db.Model):
    __tablename__ = 'project_types'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name        = db.Column(db.String(120), nullable=False)
    icon        = db.Column(db.String(20), nullable=True)
    description = db.Column(db.String(300), nullable=True)
    tag         = db.Column(db.String(60), nullable=False)
    is_active   = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    questions = db.relationship(
        'TemplateQuestion', backref='project_type', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='TemplateQuestion.step_order'
    )

    def to_dict(self) -> dict:
        return {
            'id':          self.id,
            'tenant_id':   self.tenant_id,
            'name':        self.name,
            'icon':        self.icon,
            'description': self.description,
            'tag':         self.tag,
            'is_active':   self.is_active,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ProjectType {self.name}>'
