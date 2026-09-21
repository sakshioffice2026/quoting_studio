from datetime import datetime, date
from ..extensions import db


class DeliveryStatus:
    PACKED                = 'DEL-PACKED'
    DISPATCHED            = 'DEL-DISPATCHED'
    DELIVERED             = 'DEL-DELIVERED'
    DELIVERED_WITH_ISSUES = 'DEL-DELIVERED_WITH_ISSUES'

    ALL = [PACKED, DISPATCHED, DELIVERED, DELIVERED_WITH_ISSUES]

    LABELS = {
        PACKED:                'Packed',
        DISPATCHED:            'Dispatched',
        DELIVERED:             'Delivered',
        DELIVERED_WITH_ISSUES: 'Delivered With Issues',
    }

    TERMINAL = {DELIVERED}


class DeliveryItem(db.Model):
    """
    Section 12 — one row per opening (unit) packed into a Delivery.
    """
    __tablename__ = 'delivery_items'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    delivery_id          = db.Column(db.Integer, db.ForeignKey('deliveries.id'), nullable=False, index=True)
    opening_id           = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=False, index=True)
    manufacturing_job_id = db.Column(db.Integer, db.ForeignKey('manufacturing_jobs.id'), nullable=True)

    package_label        = db.Column(db.String(100), nullable=True)
    package_count        = db.Column(db.Integer, default=1, nullable=False)

    is_damaged           = db.Column(db.Boolean, default=False, nullable=False)
    is_short             = db.Column(db.Boolean, default=False, nullable=False)
    issue_notes          = db.Column(db.Text, nullable=True)
    issue_resolved       = db.Column(db.Boolean, default=False, nullable=False)

    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    opening = db.relationship('Window', foreign_keys=[opening_id])
    job     = db.relationship('ManufacturingJob', foreign_keys=[manufacturing_job_id])

    @property
    def has_issue(self) -> bool:
        return bool(self.is_damaged or self.is_short)

    def to_dict(self) -> dict:
        return {
            'id':                   self.id,
            'delivery_id':          self.delivery_id,
            'opening_id':           self.opening_id,
            'manufacturing_job_id': self.manufacturing_job_id,
            'package_label':        self.package_label,
            'package_count':        self.package_count,
            'is_damaged':           self.is_damaged,
            'is_short':             self.is_short,
            'issue_notes':          self.issue_notes,
            'issue_resolved':       self.issue_resolved,
        }

    def __repr__(self):
        return f'<DeliveryItem {self.delivery_id}/{self.opening_id}>'


class Delivery(db.Model):
    """
    Section 12 — Delivery.
    One row per dispatch raised against a confirmed Order.
    """
    __tablename__ = 'deliveries'

    id                    = db.Column(db.Integer, primary_key=True)
    tenant_id             = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id              = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, index=True)

    delivery_number       = db.Column(db.String(40), unique=True, nullable=False)
    challan_number        = db.Column(db.String(40), nullable=True)

    status                = db.Column(db.String(40), default=DeliveryStatus.PACKED, nullable=False, index=True)

    delivery_address      = db.Column(db.Text, nullable=True)
    site_contact_name     = db.Column(db.String(200), nullable=True)
    site_contact_phone    = db.Column(db.String(50), nullable=True)

    packed_at             = db.Column(db.DateTime, nullable=True)
    packed_by             = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    scheduled_dispatch_date = db.Column(db.Date, nullable=True)
    dispatch_date         = db.Column(db.DateTime, nullable=True)
    vehicle_ref           = db.Column(db.String(100), nullable=True)
    transporter_name      = db.Column(db.String(200), nullable=True)
    driver_name           = db.Column(db.String(200), nullable=True)
    driver_phone          = db.Column(db.String(50), nullable=True)

    delivered_at          = db.Column(db.DateTime, nullable=True)
    received_by           = db.Column(db.String(200), nullable=True)
    damage_shortage_notes = db.Column(db.Text, nullable=True)
    pod_file_path         = db.Column(db.String(500), nullable=True)

    assigned_to           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at            = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order = db.relationship(
        'Order',
        backref=db.backref('deliveries', lazy='dynamic', cascade='all, delete-orphan'),
    )
    items = db.relationship(
        'DeliveryItem',
        backref='delivery',
        cascade='all, delete-orphan',
        lazy='select',
    )

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"DEL-{today.strftime('%Y%m')}"
        existing = [
            d.delivery_number for d in
            Delivery.query.filter(
                Delivery.delivery_number.like(f"{prefix}-%")
            ).with_entities(Delivery.delivery_number).all()
        ]
        last = 0
        for num in existing:
            try:
                last = max(last, int(num.rsplit('-', 1)[-1]))
            except (ValueError, IndexError):
                pass
        return f"{prefix}-{str(last + 1).zfill(3)}"

    @staticmethod
    def generate_challan_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"DC-{today.strftime('%Y%m')}"
        existing = [
            d.challan_number for d in
            Delivery.query.filter(
                Delivery.tenant_id == tenant_id,
                Delivery.challan_number.like(f"{prefix}-%")
            ).with_entities(Delivery.challan_number).all()
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
        return DeliveryStatus.LABELS.get(self.status, self.status)

    @property
    def is_delivered(self) -> bool:
        return self.status == DeliveryStatus.DELIVERED

    @property
    def has_open_issues(self) -> bool:
        return any(i.has_issue and not i.issue_resolved for i in self.items)

    def to_dict(self) -> dict:
        return {
            'id':                      self.id,
            'tenant_id':               self.tenant_id,
            'order_id':                self.order_id,
            'delivery_number':         self.delivery_number,
            'challan_number':          self.challan_number,
            'status':                  self.status,
            'status_label':            self.status_label,
            'delivery_address':        self.delivery_address,
            'site_contact_name':       self.site_contact_name,
            'site_contact_phone':      self.site_contact_phone,
            'packed_at':               self.packed_at.isoformat() if self.packed_at else None,
            'scheduled_dispatch_date': self.scheduled_dispatch_date.isoformat() if self.scheduled_dispatch_date else None,
            'dispatch_date':           self.dispatch_date.isoformat() if self.dispatch_date else None,
            'vehicle_ref':             self.vehicle_ref,
            'transporter_name':        self.transporter_name,
            'driver_name':             self.driver_name,
            'driver_phone':            self.driver_phone,
            'delivered_at':            self.delivered_at.isoformat() if self.delivered_at else None,
            'received_by':             self.received_by,
            'damage_shortage_notes':   self.damage_shortage_notes,
            'pod_file_path':           self.pod_file_path,
            'items':                   [i.to_dict() for i in self.items],
            'created_at':              self.created_at.isoformat() if self.created_at else None,
            'updated_at':              self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Delivery {self.delivery_number} {self.status}>'
