import os

from flask import Blueprint, abort, current_app, send_file

from ..models.visual_scene import VisualScene
from ..services.domain import share_link_service

public_scene_bp = Blueprint('public_scene', __name__, url_prefix='/s')


def _scene_for_quotation(tenant_id: int, quotation_id: int):
    return (VisualScene.query
            .filter_by(tenant_id=tenant_id, quotation_id=quotation_id)
            .order_by(VisualScene.id.desc())
            .first())


@public_scene_bp.after_request
def _private_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@public_scene_bp.app_context_processor
def _scene_helpers():
    def scene_composite(quotation):
        """Template helper: {'has': bool, 'version': int} for a quotation."""
        try:
            scene = _scene_for_quotation(quotation.tenant_id, quotation.id)
        except Exception:
            scene = None
        if scene is None or not scene.rendered_path:
            return {'has': False, 'version': 0}
        return {'has': True, 'version': scene.version or 1}
    return {'scene_composite': scene_composite}


@public_scene_bp.route('/<token>/visual/scene')
def scene_image(token):
    link = share_link_service.get_active_visualiser_by_token(token)
    if link is None:
        abort(404)

    scene = _scene_for_quotation(link.tenant_id, link.resource_id)
    if scene is None or not scene.rendered_path:
        abort(404)

    base = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.realpath(os.path.join(base, scene.rendered_path))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        abort(404)
    return send_file(full, mimetype='image/png')
