from ...extensions import db
from ...repositories import lead_repo
from ...models.lead import LeadStatus, FollowUpStatus
from . import customer_service


def get_lead(tenant_id: int, lead_id: int):
    return lead_repo.get_by_id(tenant_id, lead_id)


def list_leads(tenant_id: int, status: str | None = None, assigned_to: int | None = None):
    return lead_repo.list_all(tenant_id, status=status, assigned_to=assigned_to)


def create_lead(tenant_id: int, customer_name: str, phone=None, email=None, **fields):
    """Capture a new enquiry. De-dupes against existing open leads by phone/email."""
    if not customer_name or not customer_name.strip():
        raise ValueError('Customer name is required')
    if not phone and not email:
        raise ValueError('At least one of phone or email is required')

    duplicate = lead_repo.find_open_duplicate(tenant_id, phone, email)

    lead = lead_repo.create(
        tenant_id=tenant_id,
        customer_name=customer_name.strip(),
        phone=phone,
        email=email,
        status=LeadStatus.DUPLICATE if duplicate else LeadStatus.NEW,
        duplicate_of_lead_id=duplicate.id if duplicate else None,
        customer_id=duplicate.customer_id if duplicate else None,
        **fields,
    )
    db.session.commit()
    return lead


def assign_lead(tenant_id: int, lead_id: int, user_id: int):
    """Approval gate: valid phone/email + owner assigned -> LEAD-ASSIGNED."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    if lead.status in (LeadStatus.DUPLICATE, LeadStatus.INVALID):
        raise ValueError(f'Cannot assign a lead in status {lead.status}')
    if not lead.phone and not lead.email:
        raise ValueError('Lead must have a valid phone or email before assignment')

    lead_repo.update(lead, assigned_to=user_id, status=LeadStatus.ASSIGNED,
                      follow_up_status=FollowUpStatus.IN_PROGRESS)
    db.session.commit()
    return lead


def mark_invalid(tenant_id: int, lead_id: int, reason: str | None = None):
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    lead_repo.update(lead, status=LeadStatus.INVALID, lost_reason=reason)
    db.session.commit()
    return lead


def mark_duplicate(tenant_id: int, lead_id: int, duplicate_of_lead_id: int):
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    target = lead_repo.get_by_id(tenant_id, duplicate_of_lead_id)
    if not lead or not target:
        raise LookupError('Lead not found')
    lead_repo.update(lead, status=LeadStatus.DUPLICATE,
                      duplicate_of_lead_id=target.id, customer_id=target.customer_id)
    db.session.commit()
    return lead


def qualify_lead(tenant_id: int, lead_id: int):
    """Approval gate: FUP-QUALIFIED -> deduped/created Customer record."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    customer = customer_service.find_or_create_from_lead(tenant_id, lead)
    lead_repo.update(lead, follow_up_status=FollowUpStatus.QUALIFIED, customer_id=customer.id)
    db.session.commit()
    return lead


def set_follow_up_status(tenant_id: int, lead_id: int, follow_up_status: str, lost_reason: str | None = None):
    if follow_up_status not in FollowUpStatus.ALL:
        raise ValueError(f'Invalid follow-up status: {follow_up_status}')
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    if follow_up_status == FollowUpStatus.LOST and not lost_reason:
        raise ValueError('lost_reason is required when closing a lead as FUP-LOST')

    fields = {'follow_up_status': follow_up_status}
    if lost_reason:
        fields['lost_reason'] = lost_reason
    lead_repo.update(lead, **fields)
    db.session.commit()
    return lead


def update_lead(tenant_id: int, lead_id: int, **fields):
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    lead_repo.update(lead, **fields)
    db.session.commit()
    return lead


def delete_lead(tenant_id: int, lead_id: int):
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    lead_repo.delete(lead)
    db.session.commit()
