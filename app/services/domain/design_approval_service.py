import json
from datetime import datetime, timedelta

from ...extensions import db
from ...repositories import design_approval_repo
from ...models import Project, Window
from ...models.design_approval import DesignApproval, DesignApprovalStatus

# Default SLA if not overridden per-approval (matches doc: auto-reminder day 5 and day 9)
DEFAULT_APPROVAL_SLA_DAYS = 10


def get_approval(tenant_id: int, approval_id: int):
    return design_approval_repo.get_by_id(tenant_id, approval_id)


def get_latest_for_project(tenant_id: int, project_id: int):
    return design_approval_repo.get_latest_for_project(tenant_id, project_id)


def list_for_project(tenant_id: int, project_id: int):
    return design_approval_repo.list_for_project(tenant_id, project_id)


def list_approvals(tenant_id: int, status: str | None = None):
    return design_approval_repo.list_all(tenant_id, status=status)


def is_project_approved(tenant_id: int, project_id: int) -> bool:
    latest = design_approval_repo.get_latest_for_project(tenant_id, project_id)
    return bool(latest and latest.status == DesignApprovalStatus.APPROVED)


def _project_windows(tenant_id: int, project_id: int):
    return Window.query.filter_by(tenant_id=tenant_id, project_id=project_id).all()


def submit_for_approval(tenant_id: int, project_id: int, submitted_by: int, survey_id: int | None = None):
    project = Project.query.filter_by(tenant_id=tenant_id, id=project_id).first()
    if not project:
        raise LookupError('Project not found')

    windows = _project_windows(tenant_id, project_id)
    if not windows:
        raise ValueError('Project has no windows/doors to submit for design approval')

    prior = design_approval_repo.get_latest_for_project(tenant_id, project_id)
    next_revision = (prior.revision_number + 1) if prior else 1

    _ACTIVE = (DesignApprovalStatus.SUBMITTED, DesignApprovalStatus.APPROVAL_SENT,
               DesignApprovalStatus.APPROVED)
    if prior and prior.status in _ACTIVE:
        design_approval_repo.update(prior, status=DesignApprovalStatus.SUPERSEDED)

    snapshot = {str(w.id): w.design_json for w in windows}

    approval = design_approval_repo.create(
        tenant_id=tenant_id,
        project_id=project_id,
        survey_id=survey_id or (prior.survey_id if prior else None),
        revision_number=next_revision,
        status=DesignApprovalStatus.SUBMITTED,
        design_snapshot_json=json.dumps(snapshot),
        submitted_by=submitted_by,
        submitted_at=datetime.utcnow(),
        approval_sla_days=DEFAULT_APPROVAL_SLA_DAYS,
    )
    db.session.commit()
    return approval


def send_to_customer(
    tenant_id: int,
    approval_id: int,
    sent_by: int,
    sla_days: int | None = None,
):
    """Transition DESIGN-SUBMITTED → APPROVAL-SENT and stamp the SLA deadline."""
    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')
    if approval.status != DesignApprovalStatus.SUBMITTED:
        raise ValueError(
            f'Only an internally-reviewed design (DESIGN-SUBMITTED) can be sent to the customer; '
            f'current status is {approval.status}'
        )

    effective_sla = sla_days or approval.approval_sla_days or DEFAULT_APPROVAL_SLA_DAYS
    now = datetime.utcnow()

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.APPROVAL_SENT,
        sent_by=sent_by,
        sent_at=now,
        expires_at=now + timedelta(days=effective_sla),
        approval_sla_days=effective_sla,
    )
    db.session.commit()
    return approval


def resend_to_customer(
    tenant_id: int,
    approval_id: int,
    resent_by: int,
    sla_days: int | None = None,
):
    """Re-open an APPROVAL-EXPIRED approval and restart the SLA clock."""
    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')
    if approval.status != DesignApprovalStatus.APPROVAL_EXPIRED:
        raise ValueError(
            f'Only an expired approval (APPROVAL-EXPIRED) can be re-sent; '
            f'current status is {approval.status}'
        )

    effective_sla = sla_days or approval.approval_sla_days or DEFAULT_APPROVAL_SLA_DAYS
    now = datetime.utcnow()

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.APPROVAL_SENT,
        resent_by=resent_by,
        resent_at=now,
        sent_at=now,
        expires_at=now + timedelta(days=effective_sla),
        approval_sla_days=effective_sla,
    )
    db.session.commit()
    return approval


def expire_approval(tenant_id: int, approval_id: int):
    """Manually mark a single APPROVAL-SENT record as APPROVAL-EXPIRED."""
    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')
    if approval.status != DesignApprovalStatus.APPROVAL_SENT:
        raise ValueError(
            f'Only an APPROVAL-SENT record can be expired; current status is {approval.status}'
        )
    design_approval_repo.update(approval, status=DesignApprovalStatus.APPROVAL_EXPIRED)
    db.session.commit()
    return approval


def expire_overdue(tenant_id: int | None = None) -> int:
    """Batch job: flip every APPROVAL-SENT record past its expires_at to APPROVAL-EXPIRED.
    Pass tenant_id=None to run across all tenants (cron use-case).
    Returns the count of records expired.
    """
    now = datetime.utcnow()
    q = DesignApproval.query.filter(
        DesignApproval.status == DesignApprovalStatus.APPROVAL_SENT,
        DesignApproval.expires_at.isnot(None),
        DesignApproval.expires_at < now,
    )
    if tenant_id is not None:
        q = q.filter(DesignApproval.tenant_id == tenant_id)

    overdue = q.all()
    for approval in overdue:
        approval.status = DesignApprovalStatus.APPROVAL_EXPIRED

    if overdue:
        db.session.commit()
    return len(overdue)


def approve(tenant_id: int, approval_id: int, approved_by: int, customer_signoff_notes: str | None = None):
    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')

    _approvable = (DesignApprovalStatus.SUBMITTED, DesignApprovalStatus.APPROVAL_SENT)
    if approval.status not in _approvable:
        raise ValueError(f'Cannot approve a design in status {approval.status}')

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.APPROVED,
        approved_by=approved_by,
        approved_at=datetime.utcnow(),
        customer_signoff_notes=customer_signoff_notes,
    )

    for window in _project_windows(tenant_id, approval.project_id):
        window.design_locked = True
        window.design_revision = approval.revision_number

    db.session.commit()
    return approval


def request_revision(tenant_id: int, approval_id: int, requested_by: int, reason: str):
    if not reason or not reason.strip():
        raise ValueError('A reason is required to request a design revision')

    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')

    _revisable = (
        DesignApprovalStatus.SUBMITTED,
        DesignApprovalStatus.APPROVAL_SENT,
        DesignApprovalStatus.APPROVAL_EXPIRED,
        DesignApprovalStatus.APPROVED,
    )
    if approval.status not in _revisable:
        raise ValueError(f'Cannot request revision on a design in status {approval.status}')

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.REVISION_REQUESTED,
        revision_requested_by=requested_by,
        revision_requested_at=datetime.utcnow(),
        revision_requested_reason=reason.strip(),
    )

    for window in _project_windows(tenant_id, approval.project_id):
        window.design_locked = False

    db.session.commit()
    return approval
