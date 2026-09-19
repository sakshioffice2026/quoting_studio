from datetime import datetime, date, timedelta
from ..extensions import db


class QuotationStatus:
    DRAFT                     = 'QUOTE-DRAFT'
    PENDING_DISCOUNT_APPROVAL = 'QUOTE-PENDING_DISCOUNT_APPROVAL'
    SENT                      = 'QUOTE-SENT'
    NEGOTIATION               = 'QUOTE-NEGOTIATION'
    ACCEPTED                  = 'QUOTE-ACCEPTED'
    LOST                      = 'QUOTE-LOST'
    EXPIRED                   = 'QUOTE-EXPIRED'

    ALL = [
        DRAFT, PENDING_DISCOUNT_APPROVAL, SENT,
        NEGOTIATION, ACCEPTED, LOST, EXPIRED,
    ]
    LABELS = {
        DRAFT:                     'Draft',
        PENDING_DISCOUNT_APPROVAL: 'Pending Discount Approval',
        SENT:                      'Sent to Customer',
        NEGOTIATION:               'Under Negotiation',
        ACCEPTED:                  'Accepted',
        LOST:                      'Lost',
        EXPIRED:                   'Expired',
    }

    EDITABLE = {DRAFT, PENDING_DISCOUNT_APPROVAL}
    LOCKED   = {ACCEPTED}
    TERMINAL = {ACCEPTED, LOST}


class Quotation(db.Model):
    """
    Section 7 — Quotation / Presentation.
    One row per versioned quotation against an approved DesignApproval.
    """
    __tablename__ = 'quotations'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'),          nullable=False, index=True)
    project_id           = db.Column(db.Integer, db.ForeignKey('projects.id'),         nullable=False, index=True)
    design_approval_id   = db.Column(db.Integer, db.ForeignKey('design_approvals.id'), nullable=True,  index=True)

    quotation_number     = db.Column(db.String(40), unique=True, nullable=False)
    quotation_version    = db.Column(db.Integer, nullable=False, default=1)
    parent_quotation_id  = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=True, index=True)

    status               = db.Column(db.String(40), default=QuotationStatus.DRAFT, nullable=False, index=True)

    # Line items: [{opening_id, label, profile_code, qty, unit, rate, amount}, ...]
    line_items_json      = db.Column(db.Text, nullable=True)

    subtotal             = db.Column(db.Numeric(12, 2), nullable=True)
    discount_pct         = db.Column(db.Numeric(5, 2),  nullable=True, default=0)
    discount_amount      = db.Column(db.Numeric(12, 2), nullable=True, default=0)
    discount_approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    discount_approved_at = db.Column(db.DateTime, nullable=True)

    tax_rate             = db.Column(db.Numeric(5, 4), nullable=False, default=0.20)
    tax_amount           = db.Column(db.Numeric(12, 2), nullable=True)
    grand_total          = db.Column(db.Numeric(12, 2), nullable=True)

    payment_terms_template = db.Column(db.String(100), nullable=True)
    validity_days        = db.Column(db.Integer, nullable=False, default=30)
    validity_date        = db.Column(db.Date, nullable=True)

    # Workflow tracking
    prepared_by          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    sent_by              = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    sent_at              = db.Column(db.DateTime, nullable=True)

    accepted_by_name     = db.Column(db.String(200), nullable=True)
    accepted_at          = db.Column(db.DateTime, nullable=True)
    acceptance_method    = db.Column(db.String(50), nullable=True)  # e-signature / email / portal / in-person

    lost_at              = db.Column(db.DateTime, nullable=True)
    lost_reason          = db.Column(db.Text, nullable=True)

    negotiation_notes    = db.Column(db.Text, nullable=True)

    pdf_path             = db.Column(db.String(500), nullable=True)

    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project         = db.relationship('Project', backref=db.backref('quotations', lazy='dynamic'))
    design_approval = db.relationship('DesignApproval', backref=db.backref('quotations', lazy='dynamic'))

    parent = db.relationship(
        'Quotation',
        primaryjoin='Quotation.parent_quotation_id == Quotation.id',
        foreign_keys='Quotation.parent_quotation_id',
        remote_side='Quotation.id',
        backref=db.backref('revisions', lazy='dynamic'),
    )

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"QT-{today.strftime('%Y%m')}"
        existing = [
            q.quotation_number for q in
            Quotation.query.filter(
                Quotation.tenant_id == tenant_id,
                Quotation.quotation_number.like(f"{prefix}-%")
            ).with_entities(Quotation.quotation_number).all()
        ]
        last = 0
        for num in existing:
            try:
                last = max(last, int(num.rsplit('-', 1)[-1]))
            except (ValueError, IndexError):
                pass
        return f"{prefix}-{str(last + 1).zfill(3)}"

    # ------------------------------------------------------------------ #
    #  Properties
    # ------------------------------------------------------------------ #
    @property
    def status_label(self) -> str:
        return QuotationStatus.LABELS.get(self.status, self.status)

    @property
    def is_editable(self) -> bool:
        return self.status in QuotationStatus.EDITABLE

    @property
    def is_expired(self) -> bool:
        if self.status == QuotationStatus.EXPIRED:
            return True
        if self.validity_date and self.status == QuotationStatus.SENT:
            return date.today() > self.validity_date
        return False

    @property
    def days_until_expiry(self) -> int | None:
        if not self.validity_date:
            return None
        return (self.validity_date - date.today()).days

    @property
    def discount_approved(self) -> bool:
        return self.discount_approved_by is not None

    import json as _json

    @property
    def line_items(self) -> list:
        if not self.line_items_json:
            return []
        try:
            import json
            return json.loads(self.line_items_json)
        except (ValueError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            'id':                   self.id,
            'tenant_id':            self.tenant_id,
            'project_id':           self.project_id,
            'design_approval_id':   self.design_approval_id,
            'quotation_number':     self.quotation_number,
            'quotation_version':    self.quotation_version,
            'parent_quotation_id':  self.parent_quotation_id,
            'status':               self.status,
            'status_label':         self.status_label,
            'subtotal':             float(self.subtotal)      if self.subtotal      else None,
            'discount_pct':         float(self.discount_pct) if self.discount_pct  else 0,
            'discount_amount':      float(self.discount_amount) if self.discount_amount else 0,
            'discount_approved':    self.discount_approved,
            'tax_rate':             float(self.tax_rate)      if self.tax_rate      else 0.20,
            'tax_amount':           float(self.tax_amount)    if self.tax_amount    else None,
            'grand_total':          float(self.grand_total)   if self.grand_total   else None,
            'payment_terms_template': self.payment_terms_template,
            'validity_days':        self.validity_days,
            'validity_date':        self.validity_date.isoformat() if self.validity_date else None,
            'is_expired':           self.is_expired,
            'days_until_expiry':    self.days_until_expiry,
            'sent_at':              self.sent_at.isoformat()      if self.sent_at      else None,
            'accepted_at':          self.accepted_at.isoformat()  if self.accepted_at  else None,
            'acceptance_method':    self.acceptance_method,
            'lost_at':              self.lost_at.isoformat()      if self.lost_at      else None,
            'lost_reason':          self.lost_reason,
            'negotiation_notes':    self.negotiation_notes,
            'created_at':           self.created_at.isoformat()   if self.created_at   else None,
            'updated_at':           self.updated_at.isoformat()   if self.updated_at   else None,
        }

    def __repr__(self):
        return f'<Quotation {self.quotation_number} v{self.quotation_version} {self.status}>'
