from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from ..models import Project, Quote, ProjectStatus

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
@login_required
def index():
    try:
        tid      = current_user.tenant_id
        projects = Project.query.filter_by(tenant_id=tid).all()
        quotes   = Quote.query.filter_by(tenant_id=tid).all()

        total    = len(projects)
        draft    = sum(1 for p in projects if p.status == ProjectStatus.DRAFT)
        sent     = sum(1 for p in projects if p.status == ProjectStatus.SENT)
        won      = sum(1 for p in projects if p.status == ProjectStatus.WON)
        lost     = sum(1 for p in projects if p.status == ProjectStatus.LOST)
        win_rate = round(won / (sent + won + lost) * 100) if (sent + won + lost) else 0

        pipeline = sum(float(q.total or 0) for q in quotes
                       if q.project and q.project.status != ProjectStatus.LOST)
        won_value= sum(float(q.total or 0) for q in quotes
                       if q.project and q.project.status == ProjectStatus.WON)
        avg_quote= round(sum(float(q.total or 0) for q in quotes) / len(quotes), 2) \
                   if quotes else 0

        # recent quotes
        from sqlalchemy import desc
        recent_quotes = (Quote.query
                         .filter_by(tenant_id=tid)
                         .order_by(desc(Quote.created_at))
                         .limit(10).all())

        stats = dict(
            total=total, draft=draft, sent=sent,
            won=won, lost=lost, win_rate=win_rate,
            pipeline=pipeline, won_value=won_value,
            avg_quote=avg_quote, quote_count=len(quotes),
        )
        return render_template('reports.html',
                               stats=stats, recent_quotes=recent_quotes)
    except Exception as exc:
        current_app.logger.exception('Reports page error: %s', exc)
        return render_template('reports.html', stats={}, recent_quotes=[])
