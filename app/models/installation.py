from datetime import datetime, date
from ..extensions import db


class InstallationStatus:
    SCHEDULED   = 'INSTALL-SCHEDULED'
    IN_PROGRESS = 'INSTALL-IN_PROGRESS'
    SNAG        = 'INSTALL-SNAG'
    COMPLETED   = 'INSTALL-COMPLETED'

    ALL = [SCHEDULED, IN_PROGRESS, SNAG, COMPLETED]

    LABELS = {
        SCHEDULED:   'Scheduled',
        IN_PROGRESS: 'In Progress',
        SNAG:        'Snag',
        COMPLETED:   'Completed',
    }

    ACTIVE   = {IN_PROGRESS, SNAG}
    TERMINAL = {COMPLETED}


class TestResult:
    PENDING = 'Pending'
    PASS    = 'Pass'
    SNAG    = 'Snag'

    ALL = [PENDING, PASS, SNAG]

    __test__ = False  # not a pytest class


class InstallationItem(db.Model):
    """
    Section 13 — one row per opening (unit) fitted in an Installation.
    """
    __tablename__ = 'installation_items'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    installation_id      = db.Column(db.Integer, db.ForeignKey('installations.id'), nullable=False, index=True)
    opening_id           = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=False, index=True)
    delivery_item_id     = db.Column(db.Integer, db.ForeignKey('delivery_items.id'), nullable=True)

    installed_by         = db.Column(db.String(200), nullable=True)
    install_date         = db.Column(db.DateTime, nullable=True)

    # Installation checklist
    fitted               = db.Column(db.Boolean, default=False, nullable=False)
    hardware_adjusted    = db.Column(db.Boolean, default=False, nullable=False)
    joints_sealed        = db.Column(db.Boolean, default=False, nullable=False)
    site_cleaned         = db.Column(db.Boolean, default=False, nullable=False)

    functional_test_result = db.Column(db.String(20), default=TestResult.PENDING, nullable=False, index=True)
    snag_list            = db.Column(db.Text, nullable=True)
    snag_resolved        = db.Column(db.Boolean, default=False, nullable=False)

    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    opening       = db.relationship('Window', foreign_keys=[opening_id])
    delivery_item = db.relationship('DeliveryItem', foreign_keys=[delivery_item_id])

    @property
    def checklist_complete(self) -> bool:
        return bool(self.fitted and self.hardware_adjusted and self.joints_sealed and self.site_cleaned)

    @property
    def has_open_snag(self) -> bool:
        return self.functional_test_result == TestResult.SNAG

    @property
    def is_passed(self) -> bool:
        return self.functional_test_result == TestResult.PASS

    def to_dict(self) -> dict:
        return {
            'id':                     self.id,
            'installation_id':        self.installation_id,
            'opening_id':             self.opening_id,
            'delivery_item_id':       self.delivery_item_id,
            'installed_by':           self.installed_by,
            'install_date':           self.install_date.isoformat() if self.install_date else None,
            'fitted':                 self.fitted,
            'hardware_adjusted':      self.hardware_adjusted,
            'joints_sealed':          self.joints_sealed,
            'site_cleaned':           self.site_cleaned,
            'functional_test_result': self.functional_test_result,
            'snag_list':              self.snag_list,
            'snag_resolved':          self.snag_resolved,
        }

    def __repr__(self):
        return f'<InstallationItem {self.installation_id}/{self.opening_id} {self.functional_test_result}>'


class Installation(db.Model):
    """
    Section 13 — Installation.
    One row per on-site fitting visit raised against a confirmed Order.
    """
    __tablename__ = 'installations'

    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id             = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, index=True)

    install_number       = db.Column(db.String(40), unique=True, nullable=False)

    status               = db.Column(db.String(40), default=InstallationStatus.SCHEDULED, nullable=False, index=True)

    installation_address = db.Column(db.Text, nullable=True)
    site_contact_name    = db.Column(db.String(200), nullable=True)
    site_contact_phone   = db.Column(db.String(50), nullable=True)

    team_lead_name       = db.Column(db.String(200), nullable=True)
    scheduled_date       = db.Column(db.Date, nullable=True)
    started_at           = db.Column(db.DateTime, nullable=True)

    completed_at         = db.Column(db.DateTime, nullable=True)
    customer_signoff_at  = db.Column(db.DateTime, nullable=True)
    signed_by            = db.Column(db.String(200), nullable=True)
    handover_notes       = db.Column(db.Text, nullable=True)
    handover_file_path   = db.Column(db.String(500), nullable=True)

    assigned_to          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at           = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order = db.relationship(
        'Order',
        backref=db.backref('installations', lazy='dynamic', cascade='all, delete-orphan'),
    )
    items = db.relationship(
        'InstallationItem',
        backref='installation',
        cascade='all, delete-orphan',
        lazy='select',
    )

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"INS-{today.strftime('%Y%m')}"
        existing = [
            i.install_number for i in
            Installation.query.filter(
                Installation.install_number.like(f"{prefix}-%")
            ).with_entities(Installation.install_number).all()
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
        return InstallationStatus.LABELS.get(self.status, self.status)

    @property
    def is_completed(self) -> bool:
        return self.status == InstallationStatus.COMPLETED

    @property
    def open_snag_count(self) -> int:
        return sum(1 for i in self.items if i.has_open_snag)

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.items if i.is_passed)

    @property
    def all_passed(self) -> bool:
        return bool(self.items) and all(i.is_passed for i in self.items)

    def to_dict(self) -> dict:
        return {
            'id':                   self.id,
            'tenant_id':            self.tenant_id,
            'order_id':             self.order_id,
            'install_number':       self.install_number,
            'status':               self.status,
            'status_label':         self.status_label,
            'installation_address': self.installation_address,
            'site_contact_name':    self.site_contact_name,
            'site_contact_phone':   self.site_contact_phone,
            'team_lead_name':       self.team_lead_name,
            'scheduled_date':       self.scheduled_date.isoformat() if self.scheduled_date else None,
            'started_at':           self.started_at.isoformat() if self.started_at else None,
            'completed_at':         self.completed_at.isoformat() if self.completed_at else None,
            'customer_signoff_at':  self.customer_signoff_at.isoformat() if self.customer_signoff_at else None,
            'signed_by':            self.signed_by,
            'handover_notes':       self.handover_notes,
            'handover_file_path':   self.handover_file_path,
            'items':                [i.to_dict() for i in self.items],
            'created_at':           self.created_at.isoformat() if self.created_at else None,
            'updated_at':           self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Installation {self.install_number} {self.status}>'
