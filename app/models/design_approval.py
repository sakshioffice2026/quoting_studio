import json
from datetime import datetime
from ..extensions import db


class DesignApprovalStatus:
    DRAFT               = 'DESIGN-DRAFT'
    SUBMITTED           = 'DESIGN-SUBMITTED'
    REVISION_REQUESTED  = 'DESIGN-REVISION_REQUESTED'
    APPROVED            = 'DESIGN-APPROVED'
    SUPERSEDED          = 'DESIGN-SUPERSEDED'

    ALL = [DRAFT, SUBMITTED, REVISION_REQUESTED, APPROVED, SUPERSEDED]
    LABELS = {
        DRAFT:              'Draft',
        SUBMITTED:          'Submitted for Approval',
        REVISION_REQUESTED: 'Revision Requested',
        APPROVED:           'Approved',
        SUPERSEDED:         'Superseded',
    }


class DesignApproval(db.Model):
    """One row per revision cycle for a Project's design. Approving a
    revision locks every Window under the project (Window.design_locked=True,
    Window.design_revision bumped); a later revision request unlocks them
    and supersedes this row."""

    __tablename__ = 'design_approvals'

    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    survey_id    = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=True, index=True)

    revision_number = db.Column(db.Integer, nullable=False, default=1)
    status           = db.Column(db.String(30), default=DesignApprovalStatus.DRAFT, nullable=False, index=True)

    design_snapshot_json = db.Column(db.Text, nullable=True)  # {window_id: design_json} at submit time

    submitted_by   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    submitted_at   = db.Column(db.DateTime, nullable=True)

    approved_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at    = db.Column(db.DateTime, nullable=True)
    customer_signoff_notes = db.Column(db.Text, nullable=True)

    revision_requested_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    revision_requested_at     = db.Column(db.DateTime, nullable=True)
    revision_requested_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    project = db.relationship('Project', backref=db.backref('design_approvals', lazy='dynamic'))
    survey  = db.relationship('Survey', backref=db.backref('design_approvals', lazy='dynamic'))

    @property
    def status_label(self) -> str:
        return DesignApprovalStatus.LABELS.get(self.status, self.status)

    @property
    def snapshot(self) -> dict:
        if not self.design_snapshot_json:
            return {}
        try:
            return json.loads(self.design_snapshot_json)
        except (ValueError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            'id':                        self.id,
            'tenant_id':                 self.tenant_id,
            'project_id':                self.project_id,
            'survey_id':                 self.survey_id,
            'revision_number':           self.revision_number,
            'status':                    self.status,
            'status_label':              self.status_label,
            'submitted_by':              self.submitted_by,
            'submitted_at':              self.submitted_at.isoformat() if self.submitted_at else None,
            'approved_by':               self.approved_by,
            'approved_at':               self.approved_at.isoformat() if self.approved_at else None,
            'customer_signoff_notes':    self.customer_signoff_notes,
            'revision_requested_by':     self.revision_requested_by,
            'revision_requested_at':     self.revision_requested_at.isoformat() if self.revision_requested_at else None,
            'revision_requested_reason': self.revision_requested_reason,
            'created_at':                self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<DesignApproval project={self.project_id} rev={self.revision_number} {self.status}>'
