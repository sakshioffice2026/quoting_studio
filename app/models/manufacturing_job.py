from datetime import datetime, date
from ..extensions import db


class ProductionStage:
    CUTTING   = 'Cutting'
    MACHINING = 'Machining'
    ASSEMBLY  = 'Assembly'
    GLAZING   = 'Glazing'
    FINISHING = 'Finishing'
    QC        = 'QC'

    ALL = [CUTTING, MACHINING, ASSEMBLY, GLAZING, FINISHING, QC]

    LABELS = {
        CUTTING:   'Cutting',
        MACHINING: 'Machining',
        ASSEMBLY:  'Assembly',
        GLAZING:   'Glazing',
        FINISHING: 'Finishing',
        QC:        'Quality Check',
    }

    ORDER = {CUTTING: 0, MACHINING: 1, ASSEMBLY: 2, GLAZING: 3, FINISHING: 4, QC: 5}


class QcResult:
    PASS   = 'Pass'
    REWORK = 'Rework'
    REJECT = 'Reject'

    ALL = [PASS, REWORK, REJECT]


class JobStatus:
    QUEUED      = 'MFG-QUEUED'
    IN_PROGRESS = 'MFG-IN_PROGRESS'
    QC_HOLD     = 'MFG-QC_HOLD'
    COMPLETED   = 'MFG-COMPLETED'

    ALL = [QUEUED, IN_PROGRESS, QC_HOLD, COMPLETED]

    LABELS = {
        QUEUED:      'Queued',
        IN_PROGRESS: 'In Progress',
        QC_HOLD:     'QC Hold',
        COMPLETED:   'Completed',
    }

    TERMINAL = {COMPLETED}


class ManufacturingJob(db.Model):
    """
    Section 11 — Manufacturing.
    One row per opening (Window) work order raised against a confirmed Order.
    """
    __tablename__ = 'manufacturing_jobs'

    id                     = db.Column(db.Integer, primary_key=True)
    tenant_id              = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    order_id               = db.Column(db.Integer, db.ForeignKey('orders.id'),  nullable=False, index=True)
    opening_id             = db.Column(db.Integer, db.ForeignKey('windows.id'), nullable=False, index=True)

    job_number             = db.Column(db.String(40), unique=True, nullable=False)

    status                 = db.Column(db.String(40), default=JobStatus.QUEUED, nullable=False, index=True)
    production_stage       = db.Column(db.String(30), default=ProductionStage.CUTTING, nullable=False)

    # Profile codes consumed: [{profile_code, qty, length_mm}, ...]
    profile_codes_json     = db.Column(db.Text, nullable=True)
    material_batch_ref     = db.Column(db.String(100), nullable=True)

    qc_result              = db.Column(db.String(20), nullable=True)
    qc_notes               = db.Column(db.Text, nullable=True)
    qc_checked_by          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    qc_checked_at          = db.Column(db.DateTime, nullable=True)

    planned_completion_date = db.Column(db.Date, nullable=True)
    actual_completion_date  = db.Column(db.Date, nullable=True)

    assigned_to            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at             = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at             = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    order   = db.relationship(
        'Order',
        backref=db.backref('manufacturing_jobs', lazy='dynamic', cascade='all, delete-orphan'),
    )
    opening = db.relationship('Window', foreign_keys=[opening_id])

    # ------------------------------------------------------------------ #
    #  Class methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_number(tenant_id: int) -> str:
        today  = date.today()
        prefix = f"MFG-{today.strftime('%Y%m')}"
        existing = [
            j.job_number for j in
            ManufacturingJob.query.filter(
                ManufacturingJob.tenant_id == tenant_id,
                ManufacturingJob.job_number.like(f"{prefix}-%")
            ).with_entities(ManufacturingJob.job_number).all()
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
        return JobStatus.LABELS.get(self.status, self.status)

    @property
    def stage_label(self) -> str:
        return ProductionStage.LABELS.get(self.production_stage, self.production_stage)

    @property
    def is_completed(self) -> bool:
        return self.status == JobStatus.COMPLETED

    @property
    def profile_codes(self) -> list:
        if not self.profile_codes_json:
            return []
        try:
            import json
            return json.loads(self.profile_codes_json)
        except (ValueError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            'id':                       self.id,
            'tenant_id':                self.tenant_id,
            'order_id':                 self.order_id,
            'opening_id':               self.opening_id,
            'job_number':               self.job_number,
            'status':                   self.status,
            'status_label':             self.status_label,
            'production_stage':         self.production_stage,
            'stage_label':              self.stage_label,
            'material_batch_ref':       self.material_batch_ref,
            'qc_result':                self.qc_result,
            'qc_notes':                 self.qc_notes,
            'qc_checked_at':            self.qc_checked_at.isoformat() if self.qc_checked_at else None,
            'planned_completion_date':  self.planned_completion_date.isoformat() if self.planned_completion_date else None,
            'actual_completion_date':   self.actual_completion_date.isoformat() if self.actual_completion_date else None,
            'created_at':               self.created_at.isoformat() if self.created_at else None,
            'updated_at':               self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ManufacturingJob {self.job_number} {self.status}>'
