from ..extensions import db
from ..models import DesignApproval


def get_by_id(tenant_id: int, approval_id: int):
    return DesignApproval.query.filter_by(tenant_id=tenant_id, id=approval_id).first()


def get_latest_for_project(tenant_id: int, project_id: int):
    return (DesignApproval.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(DesignApproval.revision_number.desc())
            .first())


def list_for_project(tenant_id: int, project_id: int):
    return (DesignApproval.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(DesignApproval.revision_number.desc())
            .all())


def list_all(tenant_id: int, status: str | None = None):
    q = DesignApproval.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(DesignApproval.created_at.desc()).all()


def create(tenant_id: int, **fields) -> DesignApproval:
    approval = DesignApproval(tenant_id=tenant_id, **fields)
    db.session.add(approval)
    db.session.flush()
    return approval


def update(approval: DesignApproval, **fields) -> DesignApproval:
    for key, value in fields.items():
        if hasattr(approval, key):
            setattr(approval, key, value)
    db.session.flush()
    return approval
