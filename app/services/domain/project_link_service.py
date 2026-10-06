"""
Project link service — unified "Project-First" flow.

Responsibilities
----------------
1. Find an existing Customer (phone / email / name search) before anything is created.
2. List a Customer's Projects so every entry point can "pick or create" a Project.
3. Attach a Lead to an existing Project (instead of the lead path creating a second one).
4. Merge two draft Quotations (line items + charges) into one master Quotation.
5. Merge two Projects of the same Customer (move windows, surveys, design approvals,
   preliminary selections, leads and quotations to the target Project).

No schema change is required.
"""
import json
from datetime import datetime
from decimal import Decimal

from ...extensions import db
from ...models import (
    Customer, Project, Window, Lead, Survey,
    PreliminarySelection, DesignApproval,
)
from ...models.project import ProjectStatus
from ...models.quotation import Quotation, QuotationStatus
from ...repositories import customer_repo, lead_repo
from . import quotation_flow_service as flow


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _get_project(tenant_id: int, project_id: int) -> Project:
    project = Project.query.filter_by(tenant_id=tenant_id, id=project_id).first()
    if not project:
        raise LookupError('Project not found')
    return project


def _get_quotation(tenant_id: int, quotation_id: int) -> Quotation:
    quotation = Quotation.query.filter_by(tenant_id=tenant_id, id=quotation_id).first()
    if not quotation:
        raise LookupError('Quotation not found')
    return quotation


# ------------------------------------------------------------------ #
#  1. Customer lookup
# ------------------------------------------------------------------ #

def search_customers(tenant_id: int, term: str | None = None) -> list[Customer]:
    """Search by name / phone / email. Used by every entry point first."""
    return customer_repo.list_all(tenant_id, search=(term or '').strip() or None)


def find_customer(tenant_id: int, phone: str | None = None, email: str | None = None):
    """Exact phone / email match, else None."""
    return customer_repo.find_by_phone_or_email(tenant_id, phone, email)


def get_or_create_customer(tenant_id: int, name: str, phone=None, email=None,
                           city=None, address=None) -> Customer:
    """Reuse an existing Customer when phone / email match; otherwise create one."""
    existing = find_customer(tenant_id, phone, email)
    if existing:
        return existing
    if not name or not name.strip():
        raise ValueError('Customer name is required')
    customer = customer_repo.create(
        tenant_id=tenant_id, name=name.strip(), phone=phone, email=email,
        city=city, address=address,
    )
    db.session.commit()
    return customer


# ------------------------------------------------------------------ #
#  2. Customer -> Projects
# ------------------------------------------------------------------ #

def list_customer_projects(tenant_id: int, customer_id: int) -> list[Project]:
    return (Project.query
            .filter_by(tenant_id=tenant_id, customer_id=customer_id)
            .order_by(Project.updated_at.desc())
            .all())


def create_project_for_customer(tenant_id: int, customer_id: int, created_by: int,
                                project_name: str | None = None,
                                address: str | None = None) -> Project:
    customer = customer_repo.get_by_id(tenant_id, customer_id)
    if not customer:
        raise LookupError('Customer not found')

    project = Project(
        tenant_id=tenant_id,
        created_by=created_by,
        customer_id=customer.id,
        customer_name=customer.name,
        project_name=(project_name or '').strip() or None,
        address=address or customer.address,
        status=ProjectStatus.DRAFT,
    )
    db.session.add(project)
    db.session.commit()
    return project


def assign_customer_to_project(tenant_id: int, project_id: int, customer_id: int) -> Project:
    """Give a walk-in / unlinked Project a real Customer."""
    project = _get_project(tenant_id, project_id)
    customer = customer_repo.get_by_id(tenant_id, customer_id)
    if not customer:
        raise LookupError('Customer not found')
    project.customer_id = customer.id
    project.customer_name = customer.name
    if not project.address:
        project.address = customer.address
    db.session.commit()
    return project


# ------------------------------------------------------------------ #
#  3. Lead -> Project
# ------------------------------------------------------------------ #

def attach_lead_to_project(tenant_id: int, lead_id: int, created_by: int,
                           project_id: int | None = None,
                           new_project_name: str | None = None) -> Project:
    """
    Link a Lead to an existing Project (project_id) or create a new Project for the
    Lead's Customer. Never creates a duplicate when project_id is supplied.
    """
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')

    customer_id = lead.customer_id
    if not customer_id:
        customer = get_or_create_customer(
            tenant_id, lead.customer_name, phone=lead.phone, email=lead.email,
            city=getattr(lead, 'project_city', None),
            address=getattr(lead, 'project_address', None),
        )
        customer_id = customer.id

    if project_id:
        project = _get_project(tenant_id, project_id)
        if project.customer_id and project.customer_id != customer_id:
            raise ValueError('Selected project belongs to a different customer')
        if not project.customer_id:
            assign_customer_to_project(tenant_id, project.id, customer_id)
    else:
        project = create_project_for_customer(
            tenant_id, customer_id, created_by,
            project_name=new_project_name or lead.project_name,
            address=getattr(lead, 'project_address', None),
        )

    lead_repo.update(lead, project_id=project.id, customer_id=customer_id)
    db.session.commit()
    return project


def suggest_projects_for_lead(tenant_id: int, lead_id: int) -> list[Project]:
    """Existing Projects of the Lead's Customer (matched by phone / email)."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')

    customer_id = lead.customer_id
    if not customer_id:
        customer = find_customer(tenant_id, lead.phone, lead.email)
        customer_id = customer.id if customer else None
    if not customer_id:
        return []
    return list_customer_projects(tenant_id, customer_id)


# ------------------------------------------------------------------ #
#  4. Quotation merge
# ------------------------------------------------------------------ #

def get_active_quotation(tenant_id: int, project_id: int) -> Quotation | None:
    """Latest quotation of the Project that is not Lost / Expired."""
    return (Quotation.query
            .filter(Quotation.tenant_id == tenant_id,
                    Quotation.project_id == project_id,
                    Quotation.status.notin_([QuotationStatus.LOST, QuotationStatus.EXPIRED]))
            .order_by(Quotation.created_at.desc())
            .first())


def list_mergeable_quotations(tenant_id: int, customer_id: int,
                              exclude_id: int | None = None) -> list[Quotation]:
    """Editable quotations across all Projects of one Customer."""
    project_ids = [p.id for p in list_customer_projects(tenant_id, customer_id)]
    if not project_ids:
        return []
    q = Quotation.query.filter(
        Quotation.tenant_id == tenant_id,
        Quotation.project_id.in_(project_ids),
        Quotation.status.in_(list(QuotationStatus.EDITABLE)),
    )
    if exclude_id:
        q = q.filter(Quotation.id != exclude_id)
    return q.order_by(Quotation.created_at.desc()).all()


def merge_quotations(tenant_id: int, source_id: int, target_id: int,
                     merged_by: int | None = None) -> Quotation:
    """
    Merge SOURCE quotation into TARGET quotation.

    - Both must be editable (Draft / Pending Discount Approval).
    - Both must belong to the same Customer (or the same Project).
    - Line items and extra charges are added to TARGET, totals recomputed.
    - If SOURCE sits in a different Project, that Project is merged into TARGET's Project.
    - SOURCE is closed as Lost with a "Merged into ..." reason.
    """
    if source_id == target_id:
        raise ValueError('Cannot merge a quotation into itself')

    source = _get_quotation(tenant_id, source_id)
    target = _get_quotation(tenant_id, target_id)

    if source.status not in QuotationStatus.EDITABLE or target.status not in QuotationStatus.EDITABLE:
        raise ValueError('Only Draft quotations can be merged')

    src_project = _get_project(tenant_id, source.project_id)
    tgt_project = _get_project(tenant_id, target.project_id)

    if src_project.id != tgt_project.id:
        same_customer = (src_project.customer_id
                         and src_project.customer_id == tgt_project.customer_id)
        src_is_unlinked = not src_project.customer_id
        tgt_is_unlinked = not tgt_project.customer_id
        if not (same_customer or src_is_unlinked or tgt_is_unlinked):
            raise ValueError('Quotations belong to different customers')

    # ---- line items (skip windows already present in target) ---------- #
    items = list(target.line_items)
    existing_windows = {i.get('window_id') for i in items if i.get('window_id')}
    for item in source.line_items:
        wid = item.get('window_id')
        if wid and wid in existing_windows:
            continue
        items.append(item)
        if wid:
            existing_windows.add(wid)
    target.line_items_json = json.dumps(items)

    # ---- extra charges ------------------------------------------------ #
    target.installation_charge = _d(target.installation_charge) + _d(source.installation_charge)
    target.transport_charge = _d(target.transport_charge) + _d(source.transport_charge)
    merged_other = list(target.other_charges) + list(source.other_charges)
    target.other_charges_json = json.dumps(merged_other) if merged_other else None

    if not target.amc_offered and source.amc_offered:
        target.amc_offered = True
        target.amc_offer_tier = source.amc_offer_tier
        target.amc_price = source.amc_price

    flow.recompute_totals(target)

    # ---- project merge ------------------------------------------------ #
    if src_project.id != tgt_project.id:
        _move_project_children(tenant_id, src_project, tgt_project)

    # ---- close source ------------------------------------------------- #
    source.status = QuotationStatus.LOST
    source.lost_at = datetime.utcnow()
    source.lost_reason = f'Merged into {target.quotation_number}'
    source.updated_at = datetime.utcnow()

    db.session.commit()
    return target


# ------------------------------------------------------------------ #
#  5. Project merge
# ------------------------------------------------------------------ #

def _move_project_children(tenant_id: int, source: Project, target: Project) -> None:
    """Re-point every child record of SOURCE project to TARGET project (no commit)."""
    if not target.customer_id and source.customer_id:
        target.customer_id = source.customer_id
        target.customer_name = source.customer_name

    for model in (Window, Survey, PreliminarySelection, DesignApproval):
        (model.query
         .filter_by(project_id=source.id)
         .update({'project_id': target.id}, synchronize_session=False))

    (Lead.query
     .filter_by(tenant_id=tenant_id, project_id=source.id)
     .update({'project_id': target.id, 'customer_id': target.customer_id},
             synchronize_session=False))

    (Quotation.query
     .filter(Quotation.tenant_id == tenant_id,
             Quotation.project_id == source.id,
             Quotation.status.notin_([QuotationStatus.LOST]))
     .update({'project_id': target.id}, synchronize_session=False))

    note = f'Merged into project #{target.id}'
    source.notes = f'{source.notes}\n{note}' if source.notes else note
    source.status = ProjectStatus.LOST
    db.session.flush()


def merge_projects(tenant_id: int, source_project_id: int, target_project_id: int) -> Project:
    """Merge two Projects of the same Customer; blocked once an Order exists on SOURCE."""
    if source_project_id == target_project_id:
        raise ValueError('Cannot merge a project into itself')

    source = _get_project(tenant_id, source_project_id)
    target = _get_project(tenant_id, target_project_id)

    if source.customer_id and target.customer_id and source.customer_id != target.customer_id:
        raise ValueError('Projects belong to different customers')

    from ...models.order import Order, OrderStatus
    has_order = (Order.query
                 .filter(Order.tenant_id == tenant_id,
                         Order.project_id == source.id,
                         Order.status != OrderStatus.CANCELLED)
                 .first())
    if has_order:
        raise ValueError('Source project already has an order and cannot be merged')

    _move_project_children(tenant_id, source, target)
    db.session.commit()
    return target
