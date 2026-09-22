"""Project stage resolver + project search.

resolve_stages(tenant_id, projects) -> {project_id: info}
    info = {
        'project_no': 'PRJ-0030',
        'stage_key':  'quotation',
        'stage':      'Quotation',
        'step':       7,
        'total':      13,
        'code':       'QUOTE-SENT',
        'label':      'Sent',
        'tone':       'info' | 'success' | 'warn' | 'danger' | 'neutral',
    }

search_projects(tenant_id, q) -> list[Project]
    Matches project name, customer name, phone, email and project number (PRJ-0030 / 30).
"""
import re

from sqlalchemy import func, or_, select

from ...extensions import db
from ...models import (
    Project, Lead, Customer, PreliminarySelection, Survey, DesignApproval,
    Quotation, Order, Payment, ManufacturingJob, Delivery, Installation,
    Warranty, AmcContract,
    LeadStatus, FollowUpStatus, PreselStatus, SurveyStatus,
    DesignApprovalStatus, QuotationStatus, OrderStatus,
    PaymentStatus, PaymentStage, JobStatus, DeliveryStatus,
    InstallationStatus, WarrantyStatus, AmcStatus,
)

# ------------------------------------------------------------------ #
#  Stage catalogue (13 steps)
# ------------------------------------------------------------------ #
STAGES = [
    ('lead',      'Lead Generation'),
    ('followup',  'Follow-Up'),
    ('presel',    'Preliminary Selection'),
    ('survey',    'Survey'),
    ('design',    'Design & Specs'),
    ('approval',  'Customer Approval'),
    ('quotation', 'Quotation'),
    ('order',     'Order Acceptance'),
    ('advance',   'Advance Payment'),
    ('mfg',       'Manufacturing'),
    ('delivery',  'Delivery'),
    ('install',   'Installation'),
    ('amc',       'AMC'),
]
STAGE_LABEL = {key: label for key, label in STAGES}
STAGE_STEP  = {key: idx + 1 for idx, (key, _) in enumerate(STAGES)}
TOTAL_STEPS = len(STAGES)

_LABELS = {}
for _cls in (
    LeadStatus, FollowUpStatus, PreselStatus, SurveyStatus,
    DesignApprovalStatus, QuotationStatus, OrderStatus, PaymentStatus,
    JobStatus, DeliveryStatus, InstallationStatus, WarrantyStatus, AmcStatus,
):
    _LABELS.update(getattr(_cls, 'LABELS', {}))

_DANGER_WORDS  = ('LOST', 'DROPPED', 'CANCELLED', 'INVALID', 'REJECT', 'DUPLICATE')
_WARN_WORDS    = ('EXPIRED', 'OVERDUE', 'HOLD', 'SNAG', 'ISSUES', 'REVISION',
                  'NURTURE', 'PENDING', 'PARTIAL', 'RESCHEDULED', 'WITH_ISSUES')
_SUCCESS_WORDS = ('APPROVED', 'ACCEPTED', 'CONFIRMED', 'RECEIVED', 'COMPLETED',
                  'DELIVERED', 'ACTIVE', 'CLOSED', 'QUALIFIED', 'SHORTLISTED',
                  'RESOLVED')


def _tone(code: str) -> str:
    code = code or ''
    if any(w in code for w in _DANGER_WORDS):
        return 'danger'
    if any(w in code for w in _WARN_WORDS):
        return 'warn'
    if any(w in code for w in _SUCCESS_WORDS):
        return 'success'
    return 'info'


def project_no(project_id: int) -> str:
    return f'PRJ-{int(project_id):04d}'


def _info(pid: int, stage_key: str, code: str) -> dict:
    return {
        'project_no': project_no(pid),
        'stage_key':  stage_key,
        'stage':      STAGE_LABEL[stage_key],
        'step':       STAGE_STEP[stage_key],
        'total':      TOTAL_STEPS,
        'code':       code,
        'label':      _LABELS.get(code, code),
        'tone':       _tone(code),
    }


def _latest_by(rows, key_attr):
    """rows must already be ordered newest-first; keep the first per key."""
    out = {}
    for r in rows:
        out.setdefault(getattr(r, key_attr), r)
    return out


def _group_by(rows, key_attr):
    out = {}
    for r in rows:
        out.setdefault(getattr(r, key_attr), []).append(r)
    return out


def _mfg_code(jobs) -> str:
    codes = [j.status for j in jobs]
    if codes and all(c == JobStatus.COMPLETED for c in codes):
        return JobStatus.COMPLETED
    if JobStatus.QC_HOLD in codes:
        return JobStatus.QC_HOLD
    if JobStatus.IN_PROGRESS in codes or JobStatus.COMPLETED in codes:
        return JobStatus.IN_PROGRESS
    return JobStatus.QUEUED


# ------------------------------------------------------------------ #
#  Resolver
# ------------------------------------------------------------------ #
def resolve_stages(tenant_id: int, projects) -> dict:
    projects = list(projects)
    if not projects:
        return {}
    pids = [p.id for p in projects]

    leads = _latest_by(
        Lead.query.filter(Lead.tenant_id == tenant_id, Lead.project_id.in_(pids))
        .order_by(Lead.created_at.desc(), Lead.id.desc()).all(),
        'project_id',
    )
    presels = _latest_by(
        PreliminarySelection.query
        .filter(PreliminarySelection.tenant_id == tenant_id,
                PreliminarySelection.project_id.in_(pids))
        .order_by(PreliminarySelection.created_at.desc(),
                  PreliminarySelection.id.desc()).all(),
        'project_id',
    )
    surveys = _latest_by(
        Survey.query
        .filter(Survey.tenant_id == tenant_id, Survey.project_id.in_(pids))
        .order_by(Survey.created_at.desc(), Survey.id.desc()).all(),
        'project_id',
    )
    designs = _latest_by(
        DesignApproval.query
        .filter(DesignApproval.tenant_id == tenant_id,
                DesignApproval.project_id.in_(pids),
                DesignApproval.status != DesignApprovalStatus.SUPERSEDED)
        .order_by(DesignApproval.created_at.desc(), DesignApproval.id.desc()).all(),
        'project_id',
    )
    quotes = _latest_by(
        Quotation.query
        .filter(Quotation.tenant_id == tenant_id, Quotation.project_id.in_(pids))
        .order_by(Quotation.created_at.desc(), Quotation.id.desc()).all(),
        'project_id',
    )

    # one order per project: newest non-cancelled, else newest cancelled
    all_orders = (
        Order.query
        .filter(Order.tenant_id == tenant_id, Order.project_id.in_(pids))
        .order_by(Order.created_at.desc(), Order.id.desc()).all()
    )
    orders = {}
    for o in all_orders:
        cur = orders.get(o.project_id)
        if cur is None or (cur.status == OrderStatus.CANCELLED
                           and o.status != OrderStatus.CANCELLED):
            orders[o.project_id] = o

    oids = [o.id for o in orders.values()]
    pays = jobs = dels = insts = warrs = amcs = {}
    if oids:
        pays = _latest_by(
            Payment.query
            .filter(Payment.order_id.in_(oids),
                    Payment.payment_stage == PaymentStage.ADVANCE)
            .order_by(Payment.created_at.desc(), Payment.id.desc()).all(),
            'order_id',
        )
        jobs = _group_by(
            ManufacturingJob.query
            .filter(ManufacturingJob.order_id.in_(oids)).all(),
            'order_id',
        )
        dels = _latest_by(
            Delivery.query.filter(Delivery.order_id.in_(oids))
            .order_by(Delivery.created_at.desc(), Delivery.id.desc()).all(),
            'order_id',
        )
        insts = _latest_by(
            Installation.query.filter(Installation.order_id.in_(oids))
            .order_by(Installation.created_at.desc(), Installation.id.desc()).all(),
            'order_id',
        )
        warrs = _latest_by(
            Warranty.query.filter(Warranty.order_id.in_(oids))
            .order_by(Warranty.created_at.desc(), Warranty.id.desc()).all(),
            'order_id',
        )
        amcs = _latest_by(
            AmcContract.query.filter(AmcContract.order_id.in_(oids))
            .order_by(AmcContract.created_at.desc(), AmcContract.id.desc()).all(),
            'order_id',
        )

    result = {}
    for p in projects:
        pid = p.id
        order = orders.get(pid)

        if order is not None:
            oid = order.id
            if oid in amcs:
                result[pid] = _info(pid, 'amc', amcs[oid].status)
                continue
            if oid in warrs:
                result[pid] = _info(pid, 'amc', warrs[oid].status)
                continue
            if oid in insts:
                result[pid] = _info(pid, 'install', insts[oid].status)
                continue
            if oid in dels:
                result[pid] = _info(pid, 'delivery', dels[oid].status)
                continue
            if oid in jobs and jobs[oid]:
                result[pid] = _info(pid, 'mfg', _mfg_code(jobs[oid]))
                continue
            if order.status == OrderStatus.CONFIRMED:
                code = pays[oid].status if oid in pays else OrderStatus.CONFIRMED
                result[pid] = _info(pid, 'advance', code)
                continue
            result[pid] = _info(pid, 'order', order.status)
            continue

        if pid in quotes:
            result[pid] = _info(pid, 'quotation', quotes[pid].status)
            continue

        if pid in designs:
            d = designs[pid]
            key = 'design' if d.status in (
                DesignApprovalStatus.DRAFT, DesignApprovalStatus.SUBMITTED
            ) else 'approval'
            result[pid] = _info(pid, key, d.status)
            continue

        if pid in surveys:
            result[pid] = _info(pid, 'survey', surveys[pid].status)
            continue

        if pid in presels:
            result[pid] = _info(pid, 'presel', presels[pid].status)
            continue

        if pid in leads:
            lead = leads[pid]
            if lead.follow_up_status:
                result[pid] = _info(pid, 'followup', lead.follow_up_status)
            else:
                result[pid] = _info(pid, 'lead', lead.status)
            continue

        result[pid] = _info(pid, 'design', DesignApprovalStatus.DRAFT)

    return result


def resolve_lead_stage(lead):
    """Journey position for a lead that has no project yet.

    A Project is only created when Preliminary Selection starts, so earlier
    leads (new / assigned / follow-up / qualified) would never show on the
    journey map. Returns None for leads that must not appear (already linked
    to a project, duplicate, invalid or lost).
    """
    if lead.project_id is not None:
        return None
    if lead.status in (LeadStatus.DUPLICATE, LeadStatus.INVALID):
        return None
    if lead.follow_up_status == FollowUpStatus.LOST:
        return None
    if lead.follow_up_status:
        info = _info(lead.id, 'followup', lead.follow_up_status)
    else:
        info = _info(lead.id, 'lead', lead.status)
    info['project_no'] = None
    return info


# ------------------------------------------------------------------ #
#  Search
# ------------------------------------------------------------------ #
def _like_escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _norm_phone(col):
    expr = col
    for ch in (' ', '-', '+', '(', ')', '.'):
        expr = func.replace(expr, ch, '')
    return expr


def search_projects(tenant_id: int, q: str | None = None):
    query = Project.query.filter(Project.tenant_id == tenant_id)
    q = (q or '').strip()
    if not q:
        return query.order_by(Project.updated_at.desc()).all()

    conds = [
        Project.customer_name.ilike(f'%{_like_escape(q)}%', escape='\\'),
        Project.project_name.ilike(f'%{_like_escape(q)}%', escape='\\'),
    ]

    # project number: PRJ-0030 / prj 30 / #30 / 30
    m = re.fullmatch(r'(PRJ)?[\s\-#]*(\d+)', q, re.IGNORECASE)
    if m:
        conds.append(Project.id == int(m.group(2)))

    # phone (only when the query looks like a phone number and is not PRJ-xxxx)
    digits = re.sub(r'\D', '', q)
    looks_like_phone = bool(re.fullmatch(r'[\d\s\-\+\(\)\.]+', q)) and len(digits) >= 3
    if looks_like_phone:
        pat = f'%{digits}%'
        phone_ids = (
            select(Lead.project_id)
            .outerjoin(Customer, Lead.customer_id == Customer.id)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.project_id.isnot(None),
                or_(_norm_phone(Lead.phone).like(pat),
                    _norm_phone(Customer.phone).like(pat)),
            )
        )
        conds.append(Project.id.in_(phone_ids))
        cust_phone_ids = select(Customer.id).where(
            Customer.tenant_id == tenant_id,
            _norm_phone(Customer.phone).like(pat),
        )
        conds.append(Project.customer_id.in_(cust_phone_ids))

    # email
    if '@' in q:
        pat = f'%{_like_escape(q)}%'
        email_ids = (
            select(Lead.project_id)
            .outerjoin(Customer, Lead.customer_id == Customer.id)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.project_id.isnot(None),
                or_(Lead.email.ilike(pat, escape='\\'),
                    Customer.email.ilike(pat, escape='\\')),
            )
        )
        conds.append(Project.id.in_(email_ids))
        cust_email_ids = select(Customer.id).where(
            Customer.tenant_id == tenant_id,
            Customer.email.ilike(pat, escape='\\'),
        )
        conds.append(Project.customer_id.in_(cust_email_ids))

    return query.filter(or_(*conds)).order_by(Project.updated_at.desc()).all()
