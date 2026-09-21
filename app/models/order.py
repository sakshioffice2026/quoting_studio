from datetime import datetime, date
from ..extensions import db


class OrderStatus:
    PENDING_SIGNATURE = 'ORDER-PENDING_SIGNATURE'
    CONFIRMED         = 'ORDER-CONFIRMED'
    CANCELLED         = 'ORDER-CANCELLED'

    ALL = [PENDING_SIGNATURE, CONFIRMED, CANCELLED]

    LABELS = {
        PENDING_SIGNATURE: 'Pending Signature',
        CONFIRMED:         'Confirmed',
        CANCELLED:         'Cancelled',
    }

    EDITABLE = {PENDING_SIGNATURE}
    LOCKED   = {CONFIRMED}
    TERMINAL = {CONFIRMED, CANCELLED}


class Order(db.Model):
    """
    Section 8 — Order Acceptance.
    One row per confirmed sales order/contract generated from an accepted Quotation.
    """
    __tablename__ = 'orders'

    id                    = db.Column(db.Integer, primary_key=True)
    tenant_id             = db.Column(db.Integer, db.ForeignKey('tenants.id'),     nullable=False, index=True)
    project_id            = db.Column(db.Integer, db.ForeignKey('projects.id'),    nullable=False, index=True)
    quotation_id          = db.Column(db.Integer, db.ForeignKey('quotations.id'),  nullable=False, index=True)

    order_number          = db.Column(db.String(40), unique=True, nullable=False)
    contract_ref          = db.Column(db.String(100), nullable=True)

    status                = db.Column(db.String(40), default=OrderStatus.PENDING_SIGNATURE, nullable=False, index=True)

    order_confirmed_by_name = db.Column(db.String(200), nullable=True)
    order_confirmed_at    = db.Column(db.DateTime, nullable=True)
    confirmation_method   = db.Column(db.String(50), nullable=True)  # e-signature / email / portal / in-person

    assigned_project_manager = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    promised_delivery_date = db.Column(db.Date, nullable=True)

    total_amount          = db.Column(db.Numeric(12, 2), nullable=True)

    cancelled_at          = db.Column(db.DateTime, nullable=True)
    cancelled_reason      = db.Column(db.Text, nullable=True)

    contract_file_path    = db.Column(db.String(500), nullable=True)

    created_by            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at            = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project   = db.relationship(
        'Project',
        backref=db.backref('orders', lazy='dynamic', cascade='all, delete-orphan'),
    )
    quotation = db.relationship(
        'Quotation',
        backref=db.backref('orders', lazy='dynamic'),
    )
    project_manager = db.relationship('User', foreign_keys=[assigned_project_manager])

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"SO-{today.strftime('%Y%m')}"
        existing = [
            o.order_number for o in
            Order.query.filter(
                Order.order_number.like(f"{prefix}-%")
            ).with_entities(Order.order_number).all()
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
        return OrderStatus.LABELS.get(self.status, self.status)

    @property
    def is_confirmed(self) -> bool:
        return self.status == OrderStatus.CONFIRMED

    @property
    def is_cancelled(self) -> bool:
        return self.status == OrderStatus.CANCELLED

    def to_dict(self) -> dict:
        return {
            'id':                      self.id,
            'tenant_id':               self.tenant_id,
            'project_id':              self.project_id,
            'quotation_id':            self.quotation_id,
            'order_number':            self.order_number,
            'contract_ref':            self.contract_ref,
            'status':                  self.status,
            'status_label':            self.status_label,
            'order_confirmed_by_name': self.order_confirmed_by_name,
            'order_confirmed_at':      self.order_confirmed_at.isoformat() if self.order_confirmed_at else None,
            'confirmation_method':     self.confirmation_method,
            'assigned_project_manager': self.assigned_project_manager,
            'promised_delivery_date':  self.promised_delivery_date.isoformat() if self.promised_delivery_date else None,
            'total_amount':            float(self.total_amount) if self.total_amount else None,
            'cancelled_at':            self.cancelled_at.isoformat() if self.cancelled_at else None,
            'cancelled_reason':        self.cancelled_reason,
            'contract_file_path':      self.contract_file_path,
            'created_at':              self.created_at.isoformat() if self.created_at else None,
            'updated_at':              self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Order {self.order_number} {self.status}>'
