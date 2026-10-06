import json

from flask import Blueprint, abort, current_app, render_template
from flask_login import current_user, login_required

from ..models import Project, Quotation, Window
from ..models.visual_scene import GLASS_TINTS
from ..services.domain import visual_scene_service as scene_service

visual_scene_bp = Blueprint('visual_scene', __name__)

FRAME_SWATCHES = [
    {'hex': '#E8E4DA', 'name': 'White'},
    {'hex': '#2B2F33', 'name': 'Anthracite'},
    {'hex': '#7C8AA0', 'name': 'Slate'},
    {'hex': '#5C4733', 'name': 'Bronze'},
    {'hex': '#1B2430', 'name': 'Midnight'},
    {'hex': '#4A6741', 'name': 'Sage'},
]


@visual_scene_bp.route('/projects/<int:project_id>/scene')
@login_required
def view(project_id):
    try:
        project = Project.query.filter_by(
            id=project_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        scene = scene_service.get_or_create_scene(
            current_user.tenant_id, project_id)

        windows = (Window.query
                   .filter_by(project_id=project_id,
                              tenant_id=current_user.tenant_id)
                   .order_by(Window.sequence_order)
                   .all())

        units = []
        for w in windows:
            units.append({
                'id': w.id,
                'label': w.label,
                'width_mm': w.width_mm,
                'height_mm': w.height_mm,
                'material': w.material,
                'frame_colour_hex': w.frame_colour_hex,
                'locked': bool(w.design_locked),
            })

        quotations = (Quotation.query
                      .filter_by(project_id=project_id,
                                 tenant_id=current_user.tenant_id)
                      .order_by(Quotation.id.desc())
                      .all())

        return render_template(
            'visual_scene.html',
            project=project,
            scene=scene,
            units=units,
            units_json=json.dumps(units),
            quotations=quotations,
            swatches=FRAME_SWATCHES,
            glass_tints=GLASS_TINTS,
        )
    except Exception as exc:
        current_app.logger.exception('Scene page load error: %s', exc)
        abort(500)
