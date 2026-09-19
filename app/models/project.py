from datetime import datetime
from ..extensions import db


class ProjectStatus:
    DRAFT = 'draft'
    SENT  = 'sent'
    WON   = 'won'
    LOST  = 'lost'

    ALL = [DRAFT, SENT, WON, LOST]
    LABELS = {
        DRAFT: 'Draft',
        SENT:  'Sent',
        WON:   'Won',
        LOST:  'Lost',
    }


class Project(db.Model):
    __tablename__ = 'projects'

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    created_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    customer_name = db.Column(db.String(200), nullable=False)
    address       = db.Column(db.String(500), nullable=True)
    notes         = db.Column(db.Text, nullable=True)
    facade_json   = db.Column(db.Text, nullable=True)
    status        = db.Column(db.String(20), default=ProjectStatus.DRAFT, nullable=False, index=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    windows = db.relationship(
        'Window', backref='project', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Window.sequence_order'
    )
    # `quotations` relationship is provided by the backref declared on
    # Quotation.project (see app/models/quotation.py).

    @property
    def window_count(self) -> int:
        return self.windows.count()

    @property
    def quotes(self):
        return self.quotations

    @property
    def latest_quote(self):
        from ..models.quotation import Quotation
        from sqlalchemy import desc
        return (Quotation.query
                .filter_by(project_id=self.id)
                .order_by(desc(Quotation.created_at))
                .first())

    @property
    def status_label(self) -> str:
        return ProjectStatus.LABELS.get(self.status, self.status.title())

    def __repr__(self):
        return f'<Project {self.customer_name}>'
