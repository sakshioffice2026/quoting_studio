from datetime import datetime, date
from ..extensions import db


class PaymentStage:
    ADVANCE        = 'Advance'
    PRE_DISPATCH   = 'Pre-Dispatch'
    ON_INSTALLATION = 'On-Installation'
    RETENTION      = 'Retention'

    ALL = [ADVANCE, PRE_DISPATCH, ON_INSTALLATION, RETENTION]

    LABELS = {
        ADVANCE:         'Advance',
        PRE_DISPATCH:    'Pre-Dispatch',
        ON_INSTALLATION: 'On-Installation',
        RETENTION:       'Retention',
    }


class PaymentStatus:
    INVOICED      = 'PAY-INVOICED'
    PARTIAL       = 'PAY-PARTIAL'
    RECEIVED      = 'PAY-RECEIVED'
    OVERDUE       = 'PAY-OVERDUE'
    HOLD_APPLIED  = 'PAY-HOLD_APPLIED'
    CLOSED        = 'PAY-CLOSED'

    ALL = [INVOICED, PARTIAL, RECEIVED, OVERDUE, HOLD_APPLIED, CLOSED]

    LABELS = {
        INVOICED:     'Invoiced',
        PARTIAL:      'Partially Received',
        RECEIVED:     'Received',
        OVERDUE:      'Overdue',
        HOLD_APPLIED: 'Hold Applied',
        CLOSED:       'Closed',
    }

    OPEN     = {INVOICED, PARTIAL, OVERDUE, HOLD_APPLIED}
    TERMINAL = {RECEIVED, CLOSED}


class Payment(db.Model):
    """
    Section 9 — Advance Payment / Section 10 — Payment Journey (Milestone Billing).
    One row per milestone invoice raised against an Order.
    """
    __tablename__ = 'payments'

    id                = db.Column(db.Integer, primary_key=True)
    tenant_id         = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id          = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, index=True)

    payment_number    = db.Column(db.String(40), unique=True, nullable=False)
    payment_stage     = db.Column(db.String(30), nullable=False, default=PaymentStage.ADVANCE)

    status            = db.Column(db.String(40), default=PaymentStatus.INVOICED, nullable=False, index=True)

    invoice_amount    = db.Column(db.Numeric(12, 2), nullable=False)
    amount_received   = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    due_date          = db.Column(db.Date, nullable=True)

    payment_mode      = db.Column(db.String(50), nullable=True)   # bank transfer / card / cheque / financing
    transaction_ref   = db.Column(db.String(100), nullable=True)
    received_at       = db.Column(db.DateTime, nullable=True)

    hold_flag         = db.Column(db.Boolean, nullable=False, default=False)
    hold_reason       = db.Column(db.Text, nullable=True)

    invoice_file_path = db.Column(db.String(500), nullable=True)
    receipt_file_path = db.Column(db.String(500), nullable=True)

    raised_by         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    order = db.relationship(
        'Order',
        backref=db.backref('payments', lazy='dynamic', cascade='all, delete-orphan'),
    )

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"PAY-{today.strftime('%Y%m')}"
        existing = [
            p.payment_number for p in
            Payment.query.filter(
                Payment.payment_number.like(f"{prefix}-%")
            ).with_entities(Payment.payment_number).all()
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
        return PaymentStatus.LABELS.get(self.status, self.status)

    @property
    def stage_label(self) -> str:
        return PaymentStage.LABELS.get(self.payment_stage, self.payment_stage)

    @property
    def balance(self):
        inv = self.invoice_amount or 0
        rec = self.amount_received or 0
        return inv - rec

    @property
    def is_fully_received(self) -> bool:
        return self.amount_received is not None and self.invoice_amount is not None \
            and self.amount_received >= self.invoice_amount

    @property
    def is_overdue(self) -> bool:
        if self.status in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
            return False
        if self.due_date:
            return date.today() > self.due_date
        return False

    def to_dict(self) -> dict:
        return {
            'id':                self.id,
            'tenant_id':         self.tenant_id,
            'order_id':          self.order_id,
            'payment_number':    self.payment_number,
            'payment_stage':     self.payment_stage,
            'stage_label':       self.stage_label,
            'status':            self.status,
            'status_label':      self.status_label,
            'invoice_amount':    float(self.invoice_amount) if self.invoice_amount else None,
            'amount_received':   float(self.amount_received) if self.amount_received else 0,
            'balance':           float(self.balance) if self.balance is not None else None,
            'due_date':          self.due_date.isoformat() if self.due_date else None,
            'is_overdue':        self.is_overdue,
            'payment_mode':      self.payment_mode,
            'transaction_ref':   self.transaction_ref,
            'received_at':       self.received_at.isoformat() if self.received_at else None,
            'hold_flag':         self.hold_flag,
            'hold_reason':       self.hold_reason,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
            'updated_at':        self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Payment {self.payment_number} {self.payment_stage} {self.status}>'
