from datetime import datetime, date
from ..extensions import db


# ------------------------------------------------------------------ #
#  Status / enum holders
# ------------------------------------------------------------------ #

class WarrantyStatus:
    ACTIVE = 'WARRANTY-ACTIVE'

    ALL = [ACTIVE]

    LABELS = {
        ACTIVE: 'Active',
    }


class AmcStatus:
    OFFERED = 'AMC-OFFERED'
    ACTIVE  = 'AMC-ACTIVE'
    EXPIRED = 'AMC-EXPIRED'

    ALL = [OFFERED, ACTIVE, EXPIRED]

    LABELS = {
        OFFERED: 'Offered',
        ACTIVE:  'Active',
        EXPIRED: 'Expired',
    }

    TERMINAL = {EXPIRED}


class AmcTier:
    BASIC    = 'Basic'
    STANDARD = 'Standard'
    PREMIUM  = 'Premium'

    ALL = [BASIC, STANDARD, PREMIUM]

    # Default preventive-maintenance visits per year for each tier
    VISITS = {BASIC: 1, STANDARD: 2, PREMIUM: 4}


class TicketStatus:
    OPEN        = 'TICKET-OPEN'
    IN_PROGRESS = 'TICKET-IN_PROGRESS'
    RESOLVED    = 'TICKET-RESOLVED'

    ALL = [OPEN, IN_PROGRESS, RESOLVED]

    LABELS = {
        OPEN:        'Open',
        IN_PROGRESS: 'In Progress',
        RESOLVED:    'Resolved',
    }

    ACTIVE   = {OPEN, IN_PROGRESS}
    TERMINAL = {RESOLVED}


class ServiceType:
    PREVENTIVE = 'Preventive'
    COMPLAINT  = 'Complaint'

    ALL = [PREVENTIVE, COMPLAINT]


class Coverage:
    WARRANTY   = 'Warranty'
    AMC        = 'AMC'
    CHARGEABLE = 'Chargeable'

    ALL = [WARRANTY, AMC, CHARGEABLE]


def _add_months(start: date, months: int) -> date:
    """start + N calendar months (day clamped to month length)."""
    month_index = start.month - 1 + months
    year  = start.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(start.day, days_in_month))


def _next_number(model, column, tenant_id: int, prefix_code: str) -> str:
    today  = date.today()
    prefix = f"{prefix_code}-{today.strftime('%Y%m')}"
    existing = [
        row[0] for row in
        model.query.filter(
            model.tenant_id == tenant_id,
            column.like(f"{prefix}-%")
        ).with_entities(column).all()
    ]
    last = 0
    for num in existing:
        try:
            last = max(last, int(num.rsplit('-', 1)[-1]))
        except (ValueError, IndexError):
            pass
    return f"{prefix}-{str(last + 1).zfill(3)}"


# ------------------------------------------------------------------ #
#  Warranty
# ------------------------------------------------------------------ #

class Warranty(db.Model):
    """
    Section 14 — free warranty registered once an order is fully installed.
    One row per Order.
    """
    __tablename__ = 'warranties'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id             = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, unique=True, index=True)

    warranty_number      = db.Column(db.String(40), unique=True, nullable=False)
    status               = db.Column(db.String(40), default=WarrantyStatus.ACTIVE, nullable=False, index=True)

    warranty_months      = db.Column(db.Integer, default=12, nullable=False)
    warranty_start_date  = db.Column(db.Date, nullable=False)
    warranty_end_date    = db.Column(db.Date, nullable=False)
    terms                = db.Column(db.Text, nullable=True)

    created_by           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order = db.relationship(
        'Order',
        backref=db.backref('warranty', uselist=False, cascade='all, delete-orphan'),
    )

    @staticmethod
    def generate_number(tenant_id: int) -> str:
        return _next_number(Warranty, Warranty.warranty_number, tenant_id, 'WAR')

    @staticmethod
    def end_date_for(start: date, months: int) -> date:
        return _add_months(start, months)

    @property
    def status_label(self) -> str:
        return WarrantyStatus.LABELS.get(self.status, self.status)

    @property
    def in_period(self) -> bool:
        """True while today falls inside the free-warranty window."""
        return self.warranty_start_date <= date.today() <= self.warranty_end_date

    @property
    def days_remaining(self) -> int:
        return max((self.warranty_end_date - date.today()).days, 0)

    def to_dict(self) -> dict:
        return {
            'id':                  self.id,
            'tenant_id':           self.tenant_id,
            'order_id':            self.order_id,
            'warranty_number':     self.warranty_number,
            'status':              self.status,
            'status_label':        self.status_label,
            'warranty_months':     self.warranty_months,
            'warranty_start_date': self.warranty_start_date.isoformat() if self.warranty_start_date else None,
            'warranty_end_date':   self.warranty_end_date.isoformat() if self.warranty_end_date else None,
            'in_period':           self.in_period,
            'days_remaining':      self.days_remaining,
            'terms':               self.terms,
        }

    def __repr__(self):
        return f'<Warranty {self.warranty_number} {self.status}>'


# ------------------------------------------------------------------ #
#  AMC contract
# ------------------------------------------------------------------ #

class AmcContract(db.Model):
    """
    Section 14 — post-warranty Annual Maintenance Contract.
    Renewals are new rows pointing back through renewal_of_id.
    """
    __tablename__ = 'amc_contracts'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'),   nullable=False, index=True)
    order_id             = db.Column(db.Integer, db.ForeignKey('orders.id'),    nullable=False, index=True)
    warranty_id          = db.Column(db.Integer, db.ForeignKey('warranties.id'), nullable=True)
    renewal_of_id        = db.Column(db.Integer, db.ForeignKey('amc_contracts.id'), nullable=True)

    amc_number           = db.Column(db.String(40), unique=True, nullable=False)
    status               = db.Column(db.String(40), default=AmcStatus.OFFERED, nullable=False, index=True)

    plan_tier            = db.Column(db.String(20), default=AmcTier.BASIC, nullable=False)
    visits_per_year      = db.Column(db.Integer, default=1, nullable=False)
    annual_fee           = db.Column(db.Numeric(12, 2), nullable=True)

    offered_at           = db.Column(db.DateTime, nullable=True)
    amc_start_date       = db.Column(db.Date, nullable=True)
    amc_end_date         = db.Column(db.Date, nullable=True)

    activated_at         = db.Column(db.DateTime, nullable=True)
    signed_by            = db.Column(db.String(200), nullable=True)
    contract_file_path   = db.Column(db.String(500), nullable=True)
    notes                = db.Column(db.Text, nullable=True)

    created_by           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order    = db.relationship(
        'Order',
        backref=db.backref('amc_contracts', lazy='dynamic', cascade='all, delete-orphan'),
    )
    warranty = db.relationship('Warranty', foreign_keys=[warranty_id])
    renewal_of = db.relationship('AmcContract', remote_side=[id], foreign_keys=[renewal_of_id])

    @staticmethod
    def generate_number(tenant_id: int) -> str:
        return _next_number(AmcContract, AmcContract.amc_number, tenant_id, 'AMC')

    @property
    def status_label(self) -> str:
        return AmcStatus.LABELS.get(self.status, self.status)

    @property
    def is_running(self) -> bool:
        return (self.status == AmcStatus.ACTIVE
                and self.amc_start_date is not None
                and self.amc_end_date is not None
                and self.amc_start_date <= date.today() <= self.amc_end_date)

    @property
    def is_lapsed(self) -> bool:
        """ACTIVE contract whose end date has passed — needs to flip to AMC-EXPIRED."""
        return (self.status == AmcStatus.ACTIVE
                and self.amc_end_date is not None
                and date.today() > self.amc_end_date)

    @property
    def days_to_expiry(self):
        if not self.amc_end_date:
            return None
        return (self.amc_end_date - date.today()).days

    def to_dict(self) -> dict:
        return {
            'id':               self.id,
            'tenant_id':        self.tenant_id,
            'order_id':         self.order_id,
            'warranty_id':      self.warranty_id,
            'renewal_of_id':    self.renewal_of_id,
            'amc_number':       self.amc_number,
            'status':           self.status,
            'status_label':     self.status_label,
            'plan_tier':        self.plan_tier,
            'visits_per_year':  self.visits_per_year,
            'annual_fee':       float(self.annual_fee) if self.annual_fee is not None else None,
            'offered_at':       self.offered_at.isoformat() if self.offered_at else None,
            'amc_start_date':   self.amc_start_date.isoformat() if self.amc_start_date else None,
            'amc_end_date':     self.amc_end_date.isoformat() if self.amc_end_date else None,
            'activated_at':     self.activated_at.isoformat() if self.activated_at else None,
            'signed_by':        self.signed_by,
            'days_to_expiry':   self.days_to_expiry,
        }

    def __repr__(self):
        return f'<AmcContract {self.amc_number} {self.plan_tier} {self.status}>'


# ------------------------------------------------------------------ #
#  Service ticket (visit / complaint)
# ------------------------------------------------------------------ #

class ServiceTicket(db.Model):
    """
    Section 14 — one row per preventive visit or complaint.
    The resolution fields double as the service visit report.
    """
    __tablename__ = 'service_tickets'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id             = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, index=True)
    opening_id           = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=True)
    amc_contract_id      = db.Column(db.Integer, db.ForeignKey('amc_contracts.id'), nullable=True, index=True)

    ticket_number        = db.Column(db.String(40), unique=True, nullable=False)
    service_type         = db.Column(db.String(20), default=ServiceType.COMPLAINT, nullable=False, index=True)
    status               = db.Column(db.String(40), default=TicketStatus.OPEN, nullable=False, index=True)
    coverage             = db.Column(db.String(20), default=Coverage.CHARGEABLE, nullable=False)

    title                = db.Column(db.String(200), nullable=False)
    description          = db.Column(db.Text, nullable=True)
    reported_by          = db.Column(db.String(200), nullable=True)

    scheduled_date       = db.Column(db.Date, nullable=True)
    technician_name      = db.Column(db.String(200), nullable=True)
    started_at           = db.Column(db.DateTime, nullable=True)

    resolution_notes     = db.Column(db.Text, nullable=True)
    resolved_at          = db.Column(db.DateTime, nullable=True)
    resolved_by          = db.Column(db.String(200), nullable=True)

    opened_at            = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order    = db.relationship(
        'Order',
        backref=db.backref('service_tickets', lazy='dynamic', cascade='all, delete-orphan'),
    )
    opening  = db.relationship('Window', foreign_keys=[opening_id])
    contract = db.relationship('AmcContract', foreign_keys=[amc_contract_id])

    @staticmethod
    def generate_number(tenant_id: int) -> str:
        return _next_number(ServiceTicket, ServiceTicket.ticket_number, tenant_id, 'TKT')

    @property
    def status_label(self) -> str:
        return TicketStatus.LABELS.get(self.status, self.status)

    @property
    def is_active(self) -> bool:
        return self.status in TicketStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            'id':               self.id,
            'tenant_id':        self.tenant_id,
            'order_id':         self.order_id,
            'opening_id':       self.opening_id,
            'amc_contract_id':  self.amc_contract_id,
            'ticket_number':    self.ticket_number,
            'service_type':     self.service_type,
            'status':           self.status,
            'status_label':     self.status_label,
            'coverage':         self.coverage,
            'title':            self.title,
            'description':      self.description,
            'reported_by':      self.reported_by,
            'scheduled_date':   self.scheduled_date.isoformat() if self.scheduled_date else None,
            'technician_name':  self.technician_name,
            'resolution_notes': self.resolution_notes,
            'opened_at':        self.opened_at.isoformat() if self.opened_at else None,
            'resolved_at':      self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def __repr__(self):
        return f'<ServiceTicket {self.ticket_number} {self.status}>'
