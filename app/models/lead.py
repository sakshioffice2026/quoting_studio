from datetime import datetime
from ..extensions import db


class LeadStatus:
    NEW       = 'LEAD-NEW'
    ASSIGNED  = 'LEAD-ASSIGNED'
    DUPLICATE = 'LEAD-DUPLICATE'
    INVALID   = 'LEAD-INVALID'

    ALL = [NEW, ASSIGNED, DUPLICATE, INVALID]
    LABELS = {
        NEW:       'New',
        ASSIGNED:  'Assigned',
        DUPLICATE: 'Duplicate',
        INVALID:   'Invalid',
    }


class FollowUpStatus:
    IN_PROGRESS = 'FUP-IN_PROGRESS'
    QUALIFIED   = 'FUP-QUALIFIED'
    NURTURE     = 'FUP-NURTURE'
    LOST        = 'FUP-LOST'

    ALL = [IN_PROGRESS, QUALIFIED, NURTURE, LOST]
    LABELS = {
        IN_PROGRESS: 'In Progress',
        QUALIFIED:   'Qualified',
        NURTURE:     'Nurture',
        LOST:        'Lost',
    }


class ProductInterest:
    DOORS   = 'doors'
    WINDOWS = 'windows'
    BOTH    = 'both'

    ALL = [DOORS, WINDOWS, BOTH]


class SourceChannel:
    WEBSITE   = 'website'
    CALL      = 'call'
    WALK_IN   = 'walk_in'
    REFERRAL  = 'referral'
    ARCHITECT = 'architect'
    EXHIBITION = 'exhibition'
    SOCIAL    = 'social'

    ALL = [WEBSITE, CALL, WALK_IN, REFERRAL, ARCHITECT, EXHIBITION, SOCIAL]


class Lead(db.Model):
    __tablename__ = 'leads'

    id                 = db.Column(db.Integer, primary_key=True)
    tenant_id          = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id        = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    project_id         = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True, index=True)

    # raw enquiry capture (kept even after dedup/merge into a Customer)
    source_channel     = db.Column(db.String(30), nullable=False, default=SourceChannel.WEBSITE)
    customer_name      = db.Column(db.String(200), nullable=False)
    project_name       = db.Column(db.String(200), nullable=True)
    phone              = db.Column(db.String(30), nullable=True, index=True)
    email              = db.Column(db.String(200), nullable=True, index=True)
    project_city       = db.Column(db.String(120), nullable=True)
    project_address    = db.Column(db.String(500), nullable=True)
    product_interest   = db.Column(db.String(20), nullable=True)
    approx_quantity    = db.Column(db.Integer, nullable=True)
    budget_band        = db.Column(db.String(60), nullable=True)

    assigned_to        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    status              = db.Column(db.String(20), default=LeadStatus.NEW, nullable=False, index=True)
    follow_up_status     = db.Column(db.String(20), nullable=True, index=True)
    duplicate_of_lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=True)
    lost_reason           = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    assignee = db.relationship('User', foreign_keys=[assigned_to])
    duplicate_of = db.relationship('Lead', remote_side=[id])
    interactions = db.relationship(
        'Interaction', backref='lead', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Interaction.created_at'
    )

    @property
    def status_label(self) -> str:
        return LeadStatus.LABELS.get(self.status, self.status)

    @property
    def follow_up_status_label(self) -> str:
        return FollowUpStatus.LABELS.get(self.follow_up_status, self.follow_up_status or '')

    @property
    def display_name(self) -> str:
        """Project name shown everywhere; falls back to the customer name."""
        return (self.project_name or '').strip() or self.customer_name

    def to_dict(self) -> dict:
        return {
            'id':                self.id,
            'tenant_id':         self.tenant_id,
            'customer_id':       self.customer_id,
            'project_id':        self.project_id,
            'source_channel':    self.source_channel,
            'customer_name':     self.customer_name,
            'project_name':      self.project_name,
            'phone':             self.phone,
            'email':             self.email,
            'project_city':      self.project_city,
            'project_address':   self.project_address,
            'product_interest':  self.product_interest,
            'approx_quantity':   self.approx_quantity,
            'budget_band':       self.budget_band,
            'assigned_to':       self.assigned_to,
            'status':            self.status,
            'follow_up_status':  self.follow_up_status,
            'lost_reason':       self.lost_reason,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Lead {self.customer_name} {self.status}>'
