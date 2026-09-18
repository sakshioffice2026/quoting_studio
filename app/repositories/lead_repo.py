from ..extensions import db
from ..models import Lead


def get_by_id(tenant_id: int, lead_id: int):
    return Lead.query.filter_by(tenant_id=tenant_id, id=lead_id).first()


def find_open_duplicate(tenant_id: int, phone: str | None, email: str | None):
    """Existing non-invalid/non-duplicate lead with the same phone or email."""
    q = Lead.query.filter(
        Lead.tenant_id == tenant_id,
        Lead.status.notin_(['LEAD-DUPLICATE', 'LEAD-INVALID']),
    )
    if phone:
        match = q.filter(Lead.phone == phone).first()
        if match:
            return match
    if email:
        match = q.filter(Lead.email == email).first()
        if match:
            return match
    return None


def list_all(tenant_id: int, status: str | None = None, assigned_to: int | None = None):
    q = Lead.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    if assigned_to:
        q = q.filter_by(assigned_to=assigned_to)
    return q.order_by(Lead.created_at.desc()).all()


def create(tenant_id: int, **fields) -> Lead:
    lead = Lead(tenant_id=tenant_id, **fields)
    db.session.add(lead)
    db.session.flush()
    return lead


def update(lead: Lead, **fields) -> Lead:
    for key, value in fields.items():
        if hasattr(lead, key):
            setattr(lead, key, value)
    db.session.flush()
    return lead


def delete(lead: Lead) -> None:
    db.session.delete(lead)
    db.session.flush()
