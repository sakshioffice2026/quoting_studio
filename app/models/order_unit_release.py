from datetime import datetime
from ..extensions import db


class UnitReleaseStatus:
    PENDING  = 'UNIT-PENDING'
    PARTIAL  = 'UNIT-PARTIAL'
    RELEASED = 'UNIT-RELEASED'

    ALL = [PENDING, PARTIAL, RELEASED]

    LABELS = {
        PENDING:  'Awaiting advance',
        PARTIAL:  'Partly covered',
        RELEASED: 'Released to manufacturing',
    }


class OrderUnitRelease(db.Model):
    """
    Unit-wise advance release ledger.
    One row per window / door on an Order when the Advance payment uses
    release_mode = 'unit_wise'. Received advance is allocated to units in
    priority order; a unit is released only when its full required advance
    is covered.
    """
    __tablename__ = 'order_unit_releases'

    id                = db.Column(db.Integer, primary_key=True)
    tenant_id         = db.Column(db.Integer, db.ForeignKey('tenants.id'),  nullable=False, index=True)
    order_id          = db.Column(db.Integer, db.ForeignKey('orders.id'),   nullable=False, index=True)
    payment_id        = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, index=True)
    window_id         = db.Column(db.Integer, db.ForeignKey('windows.id', ondelete='SET NULL'),
                                  nullable=True, index=True)

    stage             = db.Column(db.String(30), nullable=False, default='Advance', index=True)
    stage_pct         = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    label             = db.Column(db.String(200), nullable=True)
    unit_type         = db.Column(db.String(20), nullable=False, default='window')  # window / door

    line_amount       = db.Column(db.Numeric(12, 2), nullable=False, default=0)   # incl. tax share
    required_advance  = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    allocated_amount  = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    priority          = db.Column(db.Integer, nullable=False, default=0, index=True)
    status            = db.Column(db.String(30), nullable=False, default=UnitReleaseStatus.PENDING, index=True)
    released_at       = db.Column(db.DateTime, nullable=True)

    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order = db.relationship(
        'Order',
        backref=db.backref('unit_releases', lazy='dynamic',
                           order_by='OrderUnitRelease.priority',
                           cascade='all, delete-orphan'),
    )
    payment = db.relationship(
        'Payment',
        backref=db.backref('unit_releases', lazy='dynamic',
                           order_by='OrderUnitRelease.priority',
                           cascade='all, delete-orphan'),
    )
    window = db.relationship('Window')

    @property
    def status_label(self) -> str:
        return UnitReleaseStatus.LABELS.get(self.status, self.status)

    @property
    def is_released(self) -> bool:
        return self.status == UnitReleaseStatus.RELEASED

    @property
    def shortfall(self):
        return (self.required_advance or 0) - (self.allocated_amount or 0)

    @property
    def pct_covered(self) -> float:
        req = float(self.required_advance or 0)
        if req <= 0:
            return 0.0
        return round(min(float(self.allocated_amount or 0) / req * 100, 100.0), 2)

    def to_dict(self) -> dict:
        return {
            'id':               self.id,
            'order_id':         self.order_id,
            'payment_id':       self.payment_id,
            'window_id':        self.window_id,
            'stage':            self.stage,
            'stage_pct':        float(self.stage_pct or 0),
            'pct_covered':      self.pct_covered,
            'label':            self.label,
            'unit_type':        self.unit_type,
            'line_amount':      float(self.line_amount or 0),
            'required_advance': float(self.required_advance or 0),
            'allocated_amount': float(self.allocated_amount or 0),
            'shortfall':        float(self.shortfall or 0),
            'priority':         self.priority,
            'status':           self.status,
            'status_label':     self.status_label,
            'released_at':      self.released_at.isoformat() if self.released_at else None,
        }

    def __repr__(self):
        return f'<OrderUnitRelease order={self.order_id} window={self.window_id} {self.status}>'
