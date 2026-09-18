from ..extensions import db
from ..models import Customer


def get_by_id(tenant_id: int, customer_id: int):
    return Customer.query.filter_by(tenant_id=tenant_id, id=customer_id).first()


def find_by_phone_or_email(tenant_id: int, phone: str | None, email: str | None):
    q = Customer.query.filter_by(tenant_id=tenant_id)
    if phone:
        match = q.filter(Customer.phone == phone).first()
        if match:
            return match
    if email:
        match = q.filter(Customer.email == email).first()
        if match:
            return match
    return None


def list_all(tenant_id: int, search: str | None = None):
    q = Customer.query.filter_by(tenant_id=tenant_id)
    if search:
        like = f'%{search}%'
        q = q.filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.email.ilike(like)))
    return q.order_by(Customer.name).all()


def create(tenant_id: int, **fields) -> Customer:
    customer = Customer(tenant_id=tenant_id, **fields)
    db.session.add(customer)
    db.session.flush()
    return customer


def update(customer: Customer, **fields) -> Customer:
    for key, value in fields.items():
        if hasattr(customer, key):
            setattr(customer, key, value)
    db.session.flush()
    return customer


def delete(customer: Customer) -> None:
    db.session.delete(customer)
    db.session.flush()
