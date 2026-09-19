import json
from datetime import datetime, date

from ...extensions import db
from ...models import Project, Order
from ...models.order import OrderStatus
from ...models.payment import Payment, PaymentStatus, PaymentStage
from ...models.manufacturing_job import (
    ManufacturingJob, JobStatus, ProductionStage, QcResult,
)


# ------------------------------------------------------------------ #
#  Read helpers
# ------------------------------------------------------------------ #

def get_job(tenant_id: int, job_id: int) -> ManufacturingJob | None:
    return ManufacturingJob.query.filter_by(id=job_id, tenant_id=tenant_id).first()


def list_for_order(tenant_id: int, order_id: int) -> list[ManufacturingJob]:
    from sqlalchemy import asc
    return (ManufacturingJob.query
            .filter_by(tenant_id=tenant_id, order_id=order_id)
            .order_by(asc(ManufacturingJob.created_at))
            .all())


def list_jobs(tenant_id: int, status: str | None = None) -> list[ManufacturingJob]:
    from sqlalchemy import desc
    q = ManufacturingJob.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(desc(ManufacturingJob.created_at)).all()


def is_order_fully_manufactured(tenant_id: int, order_id: int) -> bool:
    jobs = list_for_order(tenant_id, order_id)
    return bool(jobs) and all(j.status == JobStatus.COMPLETED for j in jobs)


# ------------------------------------------------------------------ #
#  Guard: order must be CONFIRMED with advance PAY-RECEIVED
# ------------------------------------------------------------------ #

def _require_released_order(tenant_id: int, order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise LookupError('Order not found')
    if order.status != OrderStatus.CONFIRMED:
        raise ValueError(f'Order must be ORDER-CONFIRMED; status={order.status}')

    advance = Payment.query.filter_by(
        tenant_id=tenant_id, order_id=order_id, payment_stage=PaymentStage.ADVANCE
    ).first()
    if not advance or advance.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED):
        raise ValueError(
            'Advance payment must be PAY-RECEIVED before releasing the order to manufacturing.'
        )
    return order


# ------------------------------------------------------------------ #
#  Generate work orders — one job per opening (window) on the project
# ------------------------------------------------------------------ #

def generate_jobs_for_order(
    tenant_id:               int,
    order_id:                int,
    planned_completion_date: date | None = None,
) -> list[ManufacturingJob]:
    order = _require_released_order(tenant_id, order_id)

    existing = list_for_order(tenant_id, order_id)
    if existing:
        raise ValueError('Manufacturing jobs already exist for this order.')

    project = Project.query.filter_by(id=order.project_id, tenant_id=tenant_id).first()
    if not project:
        raise LookupError('Project not found')

    windows = project.windows.all()
    if not windows:
        raise ValueError('Project has no openings to manufacture.')

    jobs = []
    for w in windows:
        profile_codes = []
        if getattr(w, 'profile_system', None):
            profile_codes.append({
                'profile_code': getattr(w.profile_system, 'system_code', None) or getattr(w.profile_system, 'name', None),
                'qty': 1,
                'length_mm': None,
            })

        job = ManufacturingJob(
            tenant_id                = tenant_id,
            order_id                 = order.id,
            opening_id               = w.id,
            job_number               = ManufacturingJob.generate_number(tenant_id),
            status                   = JobStatus.QUEUED,
            production_stage         = ProductionStage.CUTTING,
            profile_codes_json       = json.dumps(profile_codes),
            planned_completion_date  = planned_completion_date,
            created_at               = datetime.utcnow(),
            updated_at               = datetime.utcnow(),
        )
        db.session.add(job)
        jobs.append(job)

    db.session.commit()
    return jobs


# ------------------------------------------------------------------ #
#  Start job  →  MFG-IN_PROGRESS
# ------------------------------------------------------------------ #

def start_job(tenant_id: int, job_id: int, assigned_to: int | None = None) -> ManufacturingJob:
    job = get_job(tenant_id, job_id)
    if not job:
        raise LookupError('Manufacturing job not found')
    if job.status != JobStatus.QUEUED:
        raise ValueError(f'Job must be MFG-QUEUED to start; status={job.status}')

    job.status      = JobStatus.IN_PROGRESS
    if assigned_to is not None:
        job.assigned_to = assigned_to
    job.updated_at  = datetime.utcnow()
    db.session.commit()
    return job


# ------------------------------------------------------------------ #
#  Advance production stage  (Cutting → Machining → ... → QC)
# ------------------------------------------------------------------ #

def advance_stage(tenant_id: int, job_id: int, material_batch_ref: str | None = None) -> ManufacturingJob:
    job = get_job(tenant_id, job_id)
    if not job:
        raise LookupError('Manufacturing job not found')
    if job.status not in (JobStatus.IN_PROGRESS, JobStatus.QC_HOLD):
        raise ValueError(f'Job must be MFG-IN_PROGRESS or MFG-QC_HOLD to advance stage; status={job.status}')

    order_map = {v: k for k, v in ProductionStage.ORDER.items()}
    current_idx = ProductionStage.ORDER.get(job.production_stage, 0)
    next_idx    = min(current_idx + 1, max(order_map.keys()))
    job.production_stage = order_map[next_idx]
    if material_batch_ref:
        job.material_batch_ref = material_batch_ref
    job.status      = JobStatus.IN_PROGRESS
    job.updated_at  = datetime.utcnow()
    db.session.commit()
    return job


# ------------------------------------------------------------------ #
#  Record QC result  →  MFG-QC_HOLD (Rework/Reject) or continue
# ------------------------------------------------------------------ #

def record_qc(
    tenant_id:      int,
    job_id:         int,
    qc_result:      str,
    qc_checked_by:  int,
    qc_notes:       str | None = None,
) -> ManufacturingJob:
    if qc_result not in QcResult.ALL:
        raise ValueError(f'Invalid QC result: {qc_result}')

    job = get_job(tenant_id, job_id)
    if not job:
        raise LookupError('Manufacturing job not found')
    if job.status not in (JobStatus.IN_PROGRESS, JobStatus.QC_HOLD):
        raise ValueError(f'Job must be MFG-IN_PROGRESS or MFG-QC_HOLD to record QC; status={job.status}')

    now = datetime.utcnow()
    job.qc_result     = qc_result
    job.qc_notes      = qc_notes
    job.qc_checked_by = qc_checked_by
    job.qc_checked_at = now
    job.updated_at    = now

    if qc_result == QcResult.PASS:
        job.status = JobStatus.IN_PROGRESS
    else:
        job.status = JobStatus.QC_HOLD

    db.session.commit()
    return job


# ------------------------------------------------------------------ #
#  Complete job  →  MFG-COMPLETED
# ------------------------------------------------------------------ #

def complete_job(tenant_id: int, job_id: int) -> ManufacturingJob:
    job = get_job(tenant_id, job_id)
    if not job:
        raise LookupError('Manufacturing job not found')
    if job.status != JobStatus.IN_PROGRESS:
        raise ValueError(f'Job must be MFG-IN_PROGRESS to complete; status={job.status}')
    if job.production_stage != ProductionStage.QC:
        raise ValueError('Job must reach the QC stage before it can be completed.')
    if job.qc_result != QcResult.PASS:
        raise ValueError('Job must have a passing QC result before it can be completed.')

    today = date.today()
    job.status                 = JobStatus.COMPLETED
    job.actual_completion_date = today
    job.updated_at             = datetime.utcnow()
    db.session.commit()
    return job
