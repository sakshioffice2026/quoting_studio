from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user

from ..models import Project, ProjectStatus

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    try:
        projects = (
            Project.query
            .filter_by(tenant_id=current_user.tenant_id)
            .order_by(Project.updated_at.desc())
            .all()
        )

        total    = len(projects)
        sent     = sum(1 for p in projects if p.status == ProjectStatus.SENT)
        won      = sum(1 for p in projects if p.status == ProjectStatus.WON)
        win_rate = round((won / total * 100) if total else 0)

        pipeline = sum(
            float(p.latest_quote.total)
            for p in projects
            if p.latest_quote and p.latest_quote.total
            and p.status != ProjectStatus.LOST
        )

        stats = dict(total=total, sent=sent, won=won,
                     win_rate=win_rate, pipeline=pipeline)

        current_app.logger.debug('Dashboard loaded for tenant=%s — %d projects',
                                  current_user.tenant_id, total)
        return render_template('dashboard.html', projects=projects, stats=stats)

    except Exception as exc:
        current_app.logger.exception('Dashboard load failed for tenant=%s: %s',
                                      current_user.tenant_id, exc)
        return render_template('dashboard.html', projects=[], stats=dict(
            total=0, sent=0, won=0, win_rate=0, pipeline=0
        ))
