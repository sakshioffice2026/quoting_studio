import json
from datetime import datetime
from ..extensions import db


class DesignApprovalStatus:
    DRAFT               = 'DESIGN-DRAFT'
    SUBMITTED           = 'DESIGN-SUBMITTED'
    REVISION_REQUESTED  = 'DESIGN-REVISION_REQUESTED'
    APPROVED            = 'DESIGN-APPROVED'
    SUPERSEDED          = 'DESIGN-SUPERSEDED'
    # Customer-facing approval states (Section 6 of workflow doc)
    APPROVAL_SENT       = 'APPROVAL-SENT'
    APPROVAL_EXPIRED    = 'APPROVAL-EXPIRED'

    ALL = [DRAFT, SUBMITTED, APPROVAL_SENT, REVISION_REQUESTED, APPROVED, APPROVAL_EXPIRED, SUPERSEDED]
    LABELS = {
        DRAFT:              'Draft',
        SUBMITTED:          'Internal Review',
        APPROVAL_SENT:      'Sent to Customer',
        REVISION_REQUESTED: 'Revision Requested',
        APPROVED:           'Approved',
        APPROVAL_EXPIRED:   'Approval Expired',
        SUPERSEDED:         'Superseded',
    }

    # statuses where the customer is actively expected to respond
    AWAITING_CUSTOMER = {APPROVAL_SENT}
    # statuses where downstream actions (quote) are unlocked
    LOCKED_STATUSES   = {APPROVED}


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

    # Customer-approval SLA tracking (APPROVAL-SENT / APPROVAL-EXPIRED)
    sent_at          = db.Column(db.DateTime, nullable=True)
    sent_by          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    expires_at       = db.Column(db.DateTime, nullable=True)   # sent_at + sla_days
    approval_sla_days = db.Column(db.Integer, nullable=False, server_default='10')  # tenant default

    # re-send tracking
    resent_at  = db.Column(db.DateTime, nullable=True)
    resent_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

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

    @property
    def is_expired(self) -> bool:
        """True when APPROVAL-SENT and the SLA deadline has passed."""
        if self.status != DesignApprovalStatus.APPROVAL_SENT:
            return False
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def days_until_expiry(self) -> int | None:
        """Signed days remaining; negative means already past deadline."""
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return delta.days

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
            # SLA / customer-approval fields
            'sent_by':                   self.sent_by,
            'sent_at':                   self.sent_at.isoformat() if self.sent_at else None,
            'expires_at':                self.expires_at.isoformat() if self.expires_at else None,
            'approval_sla_days':         self.approval_sla_days,
            'is_expired':                self.is_expired,
            'days_until_expiry':         self.days_until_expiry,
            'resent_at':                 self.resent_at.isoformat() if self.resent_at else None,
            'resent_by':                 self.resent_by,
            'created_at':                self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<DesignApproval project={self.project_id} rev={self.revision_number} {self.status}>'
