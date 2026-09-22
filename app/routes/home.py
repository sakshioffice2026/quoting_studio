from datetime import datetime

from flask import Blueprint, render_template, current_app, url_for
from flask_login import login_required, current_user

from ..models import (
    Project, ProjectStatus, Lead,
    Quotation, QuotationStatus,
    DesignApproval, DesignApprovalStatus,
    Order, OrderStatus,
    Payment, PaymentStatus,
    ManufacturingJob, JobStatus,
    Delivery, DeliveryStatus,
    Installation, InstallationStatus,
    AmcContract, AmcStatus,
)
from ..services.domain import project_stage_service

home_bp = Blueprint('home', __name__)

MAX_TOKENS_PER_STAGE = 5
MAX_CHIPS_PER_CARD   = 4


# ------------------------------------------------------------------ #
#  helpers
# ------------------------------------------------------------------ #
def _initials(name):
    parts = (name or '?').split()
    first = parts[0][0] if parts else '?'
    second = parts[1][0] if len(parts) > 1 else ''
    return (first + second).upper()


def _money(value):
    return '₹{:,.0f}'.format(float(value or 0))


def _project_of(obj):
    """Project for anything hanging off an order (or a project directly)."""
    if obj is None:
        return None
    if getattr(obj, 'project', None) is not None:
        return obj.project
    order = getattr(obj, 'order', None)
    return getattr(order, 'project', None) if order is not None else None


def _pname(obj):
    project = _project_of(obj)
    return project.display_name if project else '—'


def _derived_status(project, project_quotes):
    """Project state from the live quotation workflow (legacy status if no quotes)."""
    if not project_quotes:
        return project.status
    statuses = {q.status for q in project_quotes}
    if QuotationStatus.ACCEPTED in statuses:
        return ProjectStatus.WON
    if statuses & {QuotationStatus.SENT, QuotationStatus.NEGOTIATION}:
        return ProjectStatus.SENT
    if QuotationStatus.LOST in statuses:
        return ProjectStatus.LOST
    return ProjectStatus.DRAFT


def _attention_card(key, tone, title, hint, rows, href):
    return dict(
        key=key, tone=tone, title=title, hint=hint, href=href,
        count=len(rows),
        chips=rows[:MAX_CHIPS_PER_CARD],
        more=max(0, len(rows) - MAX_CHIPS_PER_CARD),
    )


# ------------------------------------------------------------------ #
#  Route
# ------------------------------------------------------------------ #
@home_bp.route('/home')
@login_required
def index():
    tid = current_user.tenant_id
    now = datetime.now()

    hour = now.hour
    greeting = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')
    first_name = (current_user.full_name or '').split()[0] if current_user.full_name else ''

    try:
        # ---------------- data pulls ---------------- #
        projects = (Project.query.filter_by(tenant_id=tid)
                    .order_by(Project.updated_at.desc()).all())
        quotes   = Quotation.query.filter_by(tenant_id=tid).all()
        approvals = DesignApproval.query.filter_by(tenant_id=tid).all()
        orders   = Order.query.filter_by(tenant_id=tid).all()
        payments = Payment.query.filter_by(tenant_id=tid).all()
        jobs     = ManufacturingJob.query.filter_by(tenant_id=tid).all()
        deliveries = Delivery.query.filter_by(tenant_id=tid).all()
        installs = Installation.query.filter_by(tenant_id=tid).all()
        contracts = AmcContract.query.filter_by(tenant_id=tid).all()
        leads    = Lead.query.filter_by(tenant_id=tid).all()

        # ---------------- journey map ---------------- #
        try:
            stage_info = project_stage_service.resolve_stages(tid, projects)
        except Exception as exc:
            current_app.logger.exception('Home: stage resolve failed: %s', exc)
            stage_info = {}

        stages = [
            dict(step=i, key=key, label=label, tokens=[], count=0, more=0, hot=False)
            for i, (key, label) in enumerate(project_stage_service.STAGES, start=1)
        ]
        by_step = {s['step']: s for s in stages}
        for p in projects:
            info = stage_info.get(p.id)
            if not info or info['step'] not in by_step:
                continue
            by_step[info['step']]['tokens'].append(dict(
                id=p.id,
                name=p.display_name,
                customer=p.customer_name,
                initials=_initials(p.customer_name),
                code=info['code'],
                label=info['label'],
                tone=info['tone'],
            ))
        for lead in sorted(leads, key=lambda l: l.created_at or datetime.min, reverse=True):
            info = project_stage_service.resolve_lead_stage(lead)
            if not info or info['step'] not in by_step:
                continue
            by_step[info['step']]['tokens'].append(dict(
                id=lead.id,
                name=lead.display_name,
                customer=lead.customer_name,
                initials=_initials(lead.customer_name),
                code=info['code'],
                label=info['label'],
                tone=info['tone'],
                href=url_for('leads.detail', lead_id=lead.id),
            ))
        for s in stages:
            s['count'] = len(s['tokens'])
            s['more'] = max(0, s['count'] - MAX_TOKENS_PER_STAGE)
            s['hot'] = any(t['tone'] in ('warn', 'danger') for t in s['tokens'])
            s['tokens'] = s['tokens'][:MAX_TOKENS_PER_STAGE]
        busiest = max(stages, key=lambda s: s['count']) if stages else None

        # ---------------- needs attention ---------------- #
        attention = []

        # overdue payments
        overdue = [p for p in payments
                   if p.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)
                   and (p.status == PaymentStatus.OVERDUE or p.is_overdue)]
        attention.append(_attention_card(
            'payment', 'danger', 'Payments overdue', 'Collect before production slips',
            [(f'{_pname(p)} · {_money(p.balance)}', url_for('payment.detail', payment_id=p.id))
             for p in overdue],
            url_for('payment.index', status=PaymentStatus.OVERDUE)))

        # QC hold
        qc_hold = [j for j in jobs if j.status == JobStatus.QC_HOLD]
        attention.append(_attention_card(
            'qc', 'danger', 'Jobs stuck on QC hold', 'Rework needed before they can ship',
            [(f'{_pname(j)} · {j.opening.label if j.opening else j.job_number}',
              url_for('manufacturing.detail', job_id=j.id)) for j in qc_hold],
            url_for('manufacturing.index', status=JobStatus.QC_HOLD)))

        # installation snags
        snags = [i for i in installs if i.status == InstallationStatus.SNAG]
        attention.append(_attention_card(
            'snag', 'warn', 'Open installation snags', 'Resolve and re-test to hand over',
            [(f'{_pname(i)} · {i.open_snag_count} open', url_for('installation.detail', installation_id=i.id))
             for i in snags],
            url_for('installation.index', status=InstallationStatus.SNAG)))

        # deliveries with issues
        del_issues = [d for d in deliveries if d.status == DeliveryStatus.DELIVERED_WITH_ISSUES]
        attention.append(_attention_card(
            'delivery', 'warn', 'Deliveries with issues', 'Damage or shortage to resolve',
            [(f'{_pname(d)} · {d.delivery_number}', url_for('delivery.detail', delivery_id=d.id))
             for d in del_issues],
            url_for('delivery.index', status=DeliveryStatus.DELIVERED_WITH_ISSUES)))

        # quotes about to lapse
        expiring_q = [q for q in quotes
                      if q.status == QuotationStatus.SENT
                      and q.days_until_expiry is not None and q.days_until_expiry <= 3]
        attention.append(_attention_card(
            'quote', 'warn', 'Quotations about to lapse', 'Follow up while the price is still valid',
            [(f'{_pname(q)} · {q.days_until_expiry}d left', url_for('quotation.detail', quotation_id=q.id))
             for q in expiring_q],
            url_for('quotation.index', status=QuotationStatus.SENT)))

        # design approvals waiting / needing revision
        design_wait = [a for a in approvals
                       if (a.status == DesignApprovalStatus.APPROVAL_SENT
                           and a.days_until_expiry is not None and a.days_until_expiry <= 2)
                       or a.status == DesignApprovalStatus.REVISION_REQUESTED]
        attention.append(_attention_card(
            'design', 'info', 'Designs need a decision', 'Expiring approvals and requested revisions',
            [(f'{_pname(a)} · Rev {a.revision_number}', url_for('design_approval.detail', approval_id=a.id))
             for a in design_wait],
            url_for('design_approval.index')))

        # orders waiting for signature
        unsigned = [o for o in orders if o.status == OrderStatus.PENDING_SIGNATURE]
        attention.append(_attention_card(
            'order', 'info', 'Orders awaiting signature', 'Get them confirmed to start billing',
            [(f'{_pname(o)} · {o.order_number}', url_for('order.detail', order_id=o.id)) for o in unsigned],
            url_for('order.index', status=OrderStatus.PENDING_SIGNATURE)))

        # AMC renewals
        renewals = [c for c in contracts
                    if c.status == AmcStatus.ACTIVE
                    and c.days_to_expiry is not None and c.days_to_expiry <= 60]
        attention.append(_attention_card(
            'amc', 'info', 'AMC renewals due', 'Contracts ending within 60 days',
            [(f'{_pname(c)} · {c.days_to_expiry}d left', url_for('amc.detail', contract_id=c.id))
             for c in renewals],
            url_for('amc.index')))

        # unassigned leads
        unassigned = [l for l in leads
                      if l.assigned_to is None
                      and l.status not in ('LEAD-DUPLICATE', 'LEAD-INVALID')]
        attention.append(_attention_card(
            'lead', 'info', 'Leads with no owner', 'Assign someone to start follow-up',
            [(l.display_name, url_for('leads.detail', lead_id=l.id)) for l in unassigned],
            url_for('leads.index')))

        attention = [a for a in attention if a['count']]
        tone_rank = {'danger': 0, 'warn': 1, 'info': 2}
        attention.sort(key=lambda a: (tone_rank.get(a['tone'], 3), -a['count']))
        attention_total = sum(a['count'] for a in attention)

        # ---------------- money in motion ---------------- #
        quotes_by_project = {}
        for q in quotes:
            quotes_by_project.setdefault(q.project_id, []).append(q)

        open_pipeline = 0.0
        for p in projects:
            pq = quotes_by_project.get(p.id, [])
            if not pq:
                continue
            if _derived_status(p, pq) in (ProjectStatus.DRAFT, ProjectStatus.SENT):
                latest = max(pq, key=lambda x: x.created_at)
                open_pipeline += float(latest.grand_total or 0)

        order_value = sum(float(o.total_amount or 0) for o in orders
                          if o.status == OrderStatus.CONFIRMED)
        collected = sum(float(p.amount_received or 0) for p in payments)
        outstanding = sum(
            float((p.invoice_amount or 0) - (p.amount_received or 0))
            for p in payments
            if p.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)
        )
        collected_pct = round(collected / order_value * 100) if order_value else 0

        money = dict(
            pipeline=_money(open_pipeline),
            order_value=_money(order_value),
            collected=_money(collected),
            outstanding=_money(outstanding),
            collected_pct=min(collected_pct, 999),
        )

        # ---------------- signals ---------------- #
        awaiting_customer = (
            sum(1 for q in quotes if q.status in (QuotationStatus.SENT, QuotationStatus.NEGOTIATION))
            + sum(1 for a in approvals if a.status == DesignApprovalStatus.APPROVAL_SENT)
        )
        in_production = sum(1 for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.IN_PROGRESS))
        on_site = sum(1 for i in installs
                      if i.status in (InstallationStatus.SCHEDULED, InstallationStatus.IN_PROGRESS,
                                      InstallationStatus.SNAG))
        signals = dict(
            projects=len(projects),
            awaiting_customer=awaiting_customer,
            in_production=in_production,
            on_site=on_site,
        )

        return render_template(
            'home.html',
            greeting=greeting, first_name=first_name, today=now.strftime('%A, %d %B %Y'),
            stages=stages, busiest=busiest,
            attention=attention, attention_total=attention_total,
            money=money, signals=signals,
        )

    except Exception as exc:
        current_app.logger.exception('Home dashboard failed for tenant=%s: %s', tid, exc)
        return render_template(
            'home.html',
            greeting=greeting, first_name=first_name, today=now.strftime('%A, %d %B %Y'),
            stages=[], busiest=None, attention=[], attention_total=0,
            money=dict(pipeline='₹0', order_value='₹0', collected='₹0', outstanding='₹0', collected_pct=0),
            signals=dict(projects=0, awaiting_customer=0, in_production=0, on_site=0),
        )
