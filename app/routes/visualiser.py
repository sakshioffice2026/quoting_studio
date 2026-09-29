from flask import Blueprint, render_template, current_app, abort
from flask_login import login_required, current_user
from ..models import Project, Window, Visualisation

visualiser_bp = Blueprint('visualiser', __name__)

@visualiser_bp.route('/projects/<int:project_id>/windows/<int:window_id>/visualise')
@login_required
def view(project_id, window_id):
    try:
        project = Project.query.filter_by(
            id=project_id, tenant_id=current_user.tenant_id
        ).first_or_404()
        window = Window.query.filter_by(
            id=window_id, tenant_id=current_user.tenant_id
        ).first_or_404()
        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        # all windows for Swap design dropdown
        all_windows = project.windows.order_by(Window.sequence_order).all()

        render_url = ('/uploads/' + vis.rendered_path) if (vis and vis.rendered_path) else None

        # render URL for every window in the project (used by multi-opening designs)
        render_urls = {}
        for w in all_windows:
            wv = (Visualisation.query
                  .filter_by(window_id=w.id)
                  .order_by(Visualisation.created_at.desc())
                  .first())
            if wv and wv.rendered_path:
                render_urls[w.id] = '/uploads/' + wv.rendered_path

        return render_template('visualiser.html',
                               project=project,
                               window=window,
                               vis=vis,
                               render_url=render_url,
                               render_urls=render_urls,
                               all_windows=all_windows)
    except Exception as exc:
        current_app.logger.exception('Visualiser load error: %s', exc)
        abort(500)