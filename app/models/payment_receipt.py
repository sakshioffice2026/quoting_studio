from datetime import datetime
from ..extensions import db


class PaymentReceipt(db.Model):
    """
    One row per money receipt recorded against a Payment milestone.
    Keeps the full receipt history instead of overwriting mode / reference.
    """
    __tablename__ = 'payment_receipts'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'),  nullable=False, index=True)
    payment_id      = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, index=True)

    amount          = db.Column(db.Numeric(12, 2), nullable=False)
    payment_mode    = db.Column(db.String(50), nullable=True)
    transaction_ref = db.Column(db.String(100), nullable=True)
    received_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes           = db.Column(db.Text, nullable=True)

    recorded_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payment = db.relationship(
        'Payment',
        backref=db.backref(
            'receipts', lazy='dynamic',
            order_by='PaymentReceipt.received_at',
            cascade='all, delete-orphan',
        ),
    )

    def to_dict(self) -> dict:
        return {
            'id':              self.id,
            'payment_id':      self.payment_id,
            'amount':          float(self.amount) if self.amount is not None else 0,
            'payment_mode':    self.payment_mode,
            'transaction_ref': self.transaction_ref,
            'received_at':     self.received_at.isoformat() if self.received_at else None,
            'notes':           self.notes,
            'recorded_by':     self.recorded_by,
        }

    def __repr__(self):
        return f'<PaymentReceipt {self.id} payment={self.payment_id} amount={self.amount}>'
