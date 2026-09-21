from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from ..models import Project, Quotation, QuotationStatus, ProjectStatus, Order, Payment, ManufacturingJob
from ..models.order import OrderStatus
from ..models.payment import PaymentStatus
from ..models.manufacturing_job import JobStatus
from ..models.delivery import Delivery, DeliveryStatus

reports_bp = Blueprint('reports', __name__)


def derive_project_status(project, project_quotes):
    """Project state from the live quotation workflow.
    Falls back to the legacy Project.status when a project has no quotations."""
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

@reports_bp.route('/reports')
@login_required
def index():
    try:
        tid      = current_user.tenant_id
        projects = Project.query.filter_by(tenant_id=tid).all()
        quotes   = Quotation.query.filter_by(tenant_id=tid).all()
        orders   = Order.query.filter_by(tenant_id=tid).all()
        payments = Payment.query.filter_by(tenant_id=tid).all()
        jobs     = ManufacturingJob.query.filter_by(tenant_id=tid).all()
        deliveries = Delivery.query.filter_by(tenant_id=tid).all()

        quotes_by_project = {}
        for q in quotes:
            quotes_by_project.setdefault(q.project_id, []).append(q)

        derived = {p.id: derive_project_status(p, quotes_by_project.get(p.id, []))
                   for p in projects}

        total    = len(projects)
        draft    = sum(1 for s in derived.values() if s == ProjectStatus.DRAFT)
        sent     = sum(1 for s in derived.values() if s == ProjectStatus.SENT)
        won      = sum(1 for s in derived.values() if s == ProjectStatus.WON)
        lost     = sum(1 for s in derived.values() if s == ProjectStatus.LOST)
        win_rate = round(won / (sent + won + lost) * 100) if (sent + won + lost) else 0

        # Pipeline = latest quotation per open (not lost) project
        pipeline = 0.0
        for pid, pq in quotes_by_project.items():
            if derived.get(pid) == ProjectStatus.LOST:
                continue
            latest = max(pq, key=lambda x: x.created_at)
            pipeline += float(latest.grand_total or 0)

        won_value = sum(float(q.grand_total or 0) for q in quotes
                        if q.status == QuotationStatus.ACCEPTED)
        avg_quote= round(sum(float(q.grand_total or 0) for q in quotes) / len(quotes), 2) \
                   if quotes else 0

        # Orders
        orders_confirmed = sum(1 for o in orders if o.status == OrderStatus.CONFIRMED)
        orders_pending    = sum(1 for o in orders if o.status == OrderStatus.PENDING_SIGNATURE)
        order_value       = sum(float(o.total_amount or 0) for o in orders
                                 if o.status == OrderStatus.CONFIRMED)

        # Payments
        payments_outstanding = sum(
            float((p.invoice_amount or 0) - (p.amount_received or 0))
            for p in payments if p.status not in (PaymentStatus.RECEIVED, PaymentStatus.CLOSED)
        )
        payments_overdue = sum(1 for p in payments if p.status == PaymentStatus.OVERDUE)
        payments_received_total = sum(float(p.amount_received or 0) for p in payments)

        # Manufacturing
        jobs_queued      = sum(1 for j in jobs if j.status == JobStatus.QUEUED)
        jobs_in_progress = sum(1 for j in jobs if j.status == JobStatus.IN_PROGRESS)
        jobs_qc_hold     = sum(1 for j in jobs if j.status == JobStatus.QC_HOLD)
        jobs_completed   = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)

        # Delivery
        deliveries_packed     = sum(1 for d in deliveries if d.status == DeliveryStatus.PACKED)
        deliveries_dispatched = sum(1 for d in deliveries if d.status == DeliveryStatus.DISPATCHED)
        deliveries_delivered  = sum(1 for d in deliveries if d.status == DeliveryStatus.DELIVERED)
        deliveries_issues     = sum(1 for d in deliveries if d.status == DeliveryStatus.DELIVERED_WITH_ISSUES)

        # recent quotes
        from sqlalchemy import desc
        recent_quotes = (Quotation.query
                         .filter_by(tenant_id=tid)
                         .order_by(desc(Quotation.created_at))
                         .limit(10).all())

        stats = dict(
            total=total, draft=draft, sent=sent,
            won=won, lost=lost, win_rate=win_rate,
            pipeline=pipeline, won_value=won_value,
            avg_quote=avg_quote, quote_count=len(quotes),
            orders_confirmed=orders_confirmed, orders_pending=orders_pending,
            order_value=order_value,
            payments_outstanding=payments_outstanding, payments_overdue=payments_overdue,
            payments_received_total=payments_received_total,
            jobs_queued=jobs_queued, jobs_in_progress=jobs_in_progress,
            jobs_qc_hold=jobs_qc_hold, jobs_completed=jobs_completed,
            deliveries_packed=deliveries_packed, deliveries_dispatched=deliveries_dispatched,
            deliveries_delivered=deliveries_delivered, deliveries_issues=deliveries_issues,
        )
        return render_template('reports.html',
                               stats=stats, recent_quotes=recent_quotes)
    except Exception as exc:
        current_app.logger.exception('Reports page error: %s', exc)
        return render_template('reports.html', stats={}, recent_quotes=[])
