from flask import Blueprint, render_template, current_app, request
from flask_login import login_required, current_user

from ..models import Project, ProjectStatus, Quotation
from ..services.domain import project_stage_service
from .reports import derive_project_status

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    q = (request.args.get('q') or '').strip()
    try:
        all_projects = (
            Project.query
            .filter_by(tenant_id=current_user.tenant_id)
            .order_by(Project.updated_at.desc())
            .all()
        )

        projects = (
            project_stage_service.search_projects(current_user.tenant_id, q)
            if q else all_projects
        )

        quotes_by_project = {}
        for _quote in Quotation.query.filter_by(tenant_id=current_user.tenant_id).all():
            quotes_by_project.setdefault(_quote.project_id, []).append(_quote)

        derived = {p.id: derive_project_status(p, quotes_by_project.get(p.id, []))
                   for p in all_projects}

        total    = len(all_projects)
        sent     = sum(1 for s in derived.values() if s == ProjectStatus.SENT)
        won      = sum(1 for s in derived.values() if s == ProjectStatus.WON)
        win_rate = round((won / total * 100) if total else 0)

        pipeline = sum(
            float(p.latest_quote.grand_total)
            for p in all_projects
            if p.latest_quote and p.latest_quote.grand_total
            and derived.get(p.id) != ProjectStatus.LOST
        )

        stats = dict(total=total, sent=sent, won=won,
                     win_rate=win_rate, pipeline=pipeline)

        try:
            stage_info = project_stage_service.resolve_stages(
                current_user.tenant_id, projects
            )
        except Exception as exc:
            current_app.logger.exception('Stage resolve failed for tenant=%s: %s',
                                          current_user.tenant_id, exc)
            stage_info = {}

        current_app.logger.debug('Dashboard loaded for tenant=%s — %d/%d projects (q=%r)',
                                  current_user.tenant_id, len(projects), total, q)
        return render_template('dashboard.html', projects=projects, stats=stats,
                               stage_info=stage_info, q=q)

    except Exception as exc:
        current_app.logger.exception('Dashboard load failed for tenant=%s: %s',
                                      current_user.tenant_id, exc)
        return render_template('dashboard.html', projects=[], stats=dict(
            total=0, sent=0, won=0, win_rate=0, pipeline=0
        ), stage_info={}, q=q)
