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

        # design geometry for every unit (windows AND doors) so the visualiser
        # can draw a texture client-side when no saved render exists
        import json
        designs = {}
        for w in all_windows:
            dj = None
            try:
                if getattr(w, 'design_json', None):
                    dj = json.loads(w.design_json)
            except Exception:
                dj = None
            if not isinstance(dj, dict) or not dj:
                dj = {
                    'shape': 'rectangle', 'unitType': 'window',
                    'frame': {'thickness': 68, 'color': w.frame_colour_hex},
                    'panes': [{'id': 'p1', 'x': 0, 'y': 0, 'w': 1, 'h': 1,
                               'opening': 'Fixed', 'infill': 'glass',
                               'glazingBars': []}],
                }
            dj['width'] = w.width_mm or dj.get('width') or 1200
            dj['height'] = w.height_mm or dj.get('height') or 1400
            designs[w.id] = dj

        return render_template('visualiser.html',
                               project=project,
                               window=window,
                               vis=vis,
                               render_url=render_url,
                               render_urls=render_urls,
                               designs=designs,
                               all_windows=all_windows)
    except Exception as exc:
        current_app.logger.exception('Visualiser load error: %s', exc)
        abort(500)