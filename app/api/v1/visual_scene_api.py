import base64

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ...extensions import db
from ...models.visual_scene import GLASS_TINTS
from ...services.domain import visual_scene_service as scene_service
from ._helpers import _own_window

scene_api_bp = Blueprint('api_v1_scene', __name__)

MAX_COMPOSITE_BYTES = 15 * 1024 * 1024


def _err(message, code=400):
    return jsonify({'error': str(message)}), code


def _scene_payload(scene):
    data = scene.to_dict()
    data['photo_url'] = ('/uploads/' + scene.photo_path) if scene.photo_path else None
    data['rendered_url'] = ('/uploads/' + scene.rendered_path) if scene.rendered_path else None
    data['glass_tints'] = GLASS_TINTS
    return data


# GET /api/v1/projects/<id>/scene
@scene_api_bp.route('/projects/<int:project_id>/scene', methods=['GET'])
@login_required
def get_scene(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        return jsonify(_scene_payload(scene))
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('get_scene error project=%d: %s', project_id, exc)
        return _err('Failed to load scene', 500)


# POST /api/v1/projects/<id>/scene/photo   (multipart: photo)
@scene_api_bp.route('/projects/<int:project_id>/scene/photo', methods=['POST'])
@login_required
def upload_scene_photo(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        scene_service.save_photo(scene, request.files.get('photo'))
        return jsonify(_scene_payload(scene))
    except LookupError as exc:
        return _err(exc, 404)
    except ValueError as exc:
        return _err(exc, 400)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('upload_scene_photo error project=%d: %s', project_id, exc)
        return _err('Failed to save photo', 500)


# PUT /api/v1/projects/<id>/scene/openings
@scene_api_bp.route('/projects/<int:project_id>/scene/openings', methods=['PUT'])
@login_required
def save_scene_openings(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        data = request.get_json(force=True) or {}
        scene_service.save_openings(scene, current_user.tenant_id, data.get('openings'))
        return jsonify(_scene_payload(scene))
    except LookupError as exc:
        return _err(exc, 404)
    except ValueError as exc:
        return _err(exc, 400)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_scene_openings error project=%d: %s', project_id, exc)
        return _err('Failed to save openings', 500)


# POST /api/v1/windows/<id>/scene-preview
# Unsaved options in, fresh overlay SVG + live price out. Nothing persisted.
@scene_api_bp.route('/windows/<int:window_id>/scene-preview', methods=['POST'])
@login_required
def scene_preview(window_id):
    try:
        window = _own_window(window_id)
        options = (request.get_json(force=True) or {}).get('options') or {}
        result = scene_service.preview_opening(window, current_user.tenant_id, options)
        return jsonify(result)
    except Exception as exc:
        current_app.logger.exception('scene_preview error window=%d: %s', window_id, exc)
        return _err('Failed to render preview', 500)


# POST /api/v1/windows/<id>/scene-options
# Persist options on the window, then rebuild + reprice open quotations.
@scene_api_bp.route('/windows/<int:window_id>/scene-options', methods=['POST'])
@login_required
def scene_commit_options(window_id):
    try:
        window = _own_window(window_id)
        options = (request.get_json(force=True) or {}).get('options') or {}
        committed = scene_service.commit_options(
            window, current_user.tenant_id, options)

        quotations = []
        try:
            from .visualisation import sync_quotations
            resp = sync_quotations(window_id)
            body = resp[0] if isinstance(resp, tuple) else resp
            payload = body.get_json(silent=True) or {}
            quotations = payload.get('quotations', [])
        except Exception as exc:
            current_app.logger.warning('scene sync failed window=%d: %s', window_id, exc)

        committed['quotations'] = quotations
        return jsonify(committed)
    except PermissionError as exc:
        return _err(exc, 409)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('scene_commit_options error window=%d: %s', window_id, exc)
        return _err('Failed to save options', 500)


# GET /api/v1/projects/<id>/scene/pricing
@scene_api_bp.route('/projects/<int:project_id>/scene/pricing', methods=['GET'])
@login_required
def scene_pricing(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        return jsonify(scene_service.scene_price_summary(scene, current_user.tenant_id))
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('scene_pricing error project=%d: %s', project_id, exc)
        return _err('Failed to price scene', 500)


# POST /api/v1/projects/<id>/scene/composite   (json: {image: dataURL|base64})
@scene_api_bp.route('/projects/<int:project_id>/scene/composite', methods=['POST'])
@login_required
def save_scene_composite(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        b64 = (request.get_json(force=True) or {}).get('image', '')
        if not b64:
            return _err('No image data provided')
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        try:
            png = base64.b64decode(b64)
        except Exception:
            return _err('Invalid base64 image data')
        if len(png) > MAX_COMPOSITE_BYTES:
            return _err('Composite exceeds 15 MB')
        scene_service.save_composite(scene, png)
        return jsonify(_scene_payload(scene))
    except LookupError as exc:
        return _err(exc, 404)
    except ValueError as exc:
        return _err(exc, 400)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_scene_composite error project=%d: %s', project_id, exc)
        return _err('Failed to save composite', 500)


# POST /api/v1/projects/<id>/scene/link-quotation   (json: {quotation_id})
@scene_api_bp.route('/projects/<int:project_id>/scene/link-quotation', methods=['POST'])
@login_required
def link_scene_quotation(project_id):
    try:
        scene = scene_service.get_or_create_scene(current_user.tenant_id, project_id)
        data = request.get_json(force=True) or {}
        try:
            quotation_id = int(data.get('quotation_id'))
        except (TypeError, ValueError):
            return _err('quotation_id required')
        scene_service.link_quotation(scene, current_user.tenant_id, quotation_id)
        return jsonify(_scene_payload(scene))
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('link_scene_quotation error project=%d: %s', project_id, exc)
        return _err('Failed to link quotation', 500)
