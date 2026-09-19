import json
from datetime import datetime

from ...extensions import db
from ...repositories import design_approval_repo
from ...models import Project, Window
from ...models.design_approval import DesignApprovalStatus


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

    if prior and prior.status in (DesignApprovalStatus.SUBMITTED, DesignApprovalStatus.APPROVED):
        # supersede the currently active cycle before opening a new one
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
    )
    db.session.commit()
    return approval


def approve(tenant_id: int, approval_id: int, approved_by: int, customer_signoff_notes: str | None = None):
    approval = design_approval_repo.get_by_id(tenant_id, approval_id)
    if not approval:
        raise LookupError('Design approval not found')
    if approval.status != DesignApprovalStatus.SUBMITTED:
        raise ValueError(f'Cannot approve a design in status {approval.status}')

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.APPROVED,
        approved_by=approved_by,
        approved_at=datetime.utcnow(),
        customer_signoff_notes=customer_signoff_notes,
    )

    # version lock: freeze every window's design at this revision
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
    if approval.status not in (DesignApprovalStatus.SUBMITTED, DesignApprovalStatus.APPROVED):
        raise ValueError(f'Cannot request revision on a design in status {approval.status}')

    design_approval_repo.update(
        approval,
        status=DesignApprovalStatus.REVISION_REQUESTED,
        revision_requested_by=requested_by,
        revision_requested_at=datetime.utcnow(),
        revision_requested_reason=reason.strip(),
    )

    # unlock windows so the design team can edit again
    for window in _project_windows(tenant_id, approval.project_id):
        window.design_locked = False

    db.session.commit()
    return approval
