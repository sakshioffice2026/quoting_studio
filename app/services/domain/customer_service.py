from ...extensions import db
from ...repositories import customer_repo


def get_customer(tenant_id: int, customer_id: int):
    return customer_repo.get_by_id(tenant_id, customer_id)


def list_customers(tenant_id: int, search: str | None = None):
    return customer_repo.list_all(tenant_id, search=search)


def find_or_create_from_lead(tenant_id: int, lead) -> 'Customer':
    """De-duplication: match existing customer by phone/email, else create one."""
    existing = customer_repo.find_by_phone_or_email(tenant_id, lead.phone, lead.email)
    if existing:
        return existing
    return customer_repo.create(
        tenant_id=tenant_id,
        name=lead.customer_name,
        phone=lead.phone,
        email=lead.email,
        city=lead.project_city,
        address=lead.project_address,
    )


def create_customer(tenant_id: int, name: str, phone=None, email=None, city=None, address=None, notes=None):
    if not name or not name.strip():
        raise ValueError('Customer name is required')
    customer = customer_repo.create(
        tenant_id=tenant_id, name=name.strip(), phone=phone, email=email,
        city=city, address=address, notes=notes,
    )
    db.session.commit()
    return customer


def update_customer(tenant_id: int, customer_id: int, **fields):
    customer = customer_repo.get_by_id(tenant_id, customer_id)
    if not customer:
        raise LookupError('Customer not found')
    customer_repo.update(customer, **fields)
    db.session.commit()
    return customer


def delete_customer(tenant_id: int, customer_id: int):
    customer = customer_repo.get_by_id(tenant_id, customer_id)
    if not customer:
        raise LookupError('Customer not found')
    customer_repo.delete(customer)
    db.session.commit()
