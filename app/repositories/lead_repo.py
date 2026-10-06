from ..extensions import db
from ..models import Lead


def get_by_id(tenant_id: int, lead_id: int):
    return Lead.query.filter_by(tenant_id=tenant_id, id=lead_id).first()


def _norm(value: str | None) -> str:
    return ' '.join((value or '').split()).lower()


def _same_enquiry(existing: Lead, product_interest: str | None,
                  project_name: str | None) -> bool:
    """Same contact is not enough: it is only a repeat of the same enquiry when
    the product interest matches and the project name matches (or is blank)."""
    if _norm(existing.product_interest) != _norm(product_interest):
        return False
    a, b = _norm(existing.project_name), _norm(project_name)
    return (not a) or (not b) or a == b


def find_open_duplicate(tenant_id: int, phone: str | None, email: str | None,
                        product_interest: str | None = None,
                        project_name: str | None = None):
    """Existing still-open lead that is the SAME enquiry (same phone/email,
    same product interest, same project). A returning customer with a new
    project is NOT a duplicate."""
    contact = []
    if phone:
        contact.append(Lead.phone == phone)
    if email:
        contact.append(Lead.email == email)
    if not contact:
        return None

    candidates = (
        Lead.query
        .filter(
            Lead.tenant_id == tenant_id,
            Lead.status.notin_(['LEAD-DUPLICATE', 'LEAD-INVALID']),
            db.or_(Lead.follow_up_status.is_(None),
                   Lead.follow_up_status != 'FUP-LOST'),
            db.or_(*contact),
        )
        .order_by(Lead.created_at.desc())
        .all()
    )
    for existing in candidates:
        if _same_enquiry(existing, product_interest, project_name):
            return existing
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
