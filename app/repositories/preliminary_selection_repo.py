from ..extensions import db
from ..models import PreliminarySelection


def get_by_id(tenant_id: int, presel_id: int):
    return PreliminarySelection.query.filter_by(tenant_id=tenant_id, id=presel_id).first()


def get_by_lead(tenant_id: int, lead_id: int):
    return (PreliminarySelection.query
            .filter_by(tenant_id=tenant_id, lead_id=lead_id)
            .order_by(PreliminarySelection.created_at.desc())
            .first())


def get_by_project(tenant_id: int, project_id: int):
    return (PreliminarySelection.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(PreliminarySelection.created_at.desc())
            .first())


def list_all(tenant_id: int, status: str | None = None):
    q = PreliminarySelection.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(PreliminarySelection.created_at.desc()).all()


def create(tenant_id: int, **fields) -> PreliminarySelection:
    presel = PreliminarySelection(tenant_id=tenant_id, **fields)
    db.session.add(presel)
    db.session.flush()
    return presel


def update(presel: PreliminarySelection, **fields) -> PreliminarySelection:
    for key, value in fields.items():
        if hasattr(presel, key):
            setattr(presel, key, value)
    db.session.flush()
    return presel


def delete(presel: PreliminarySelection) -> None:
    db.session.delete(presel)
    db.session.flush()
