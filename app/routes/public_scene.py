import json
import os

from flask import Blueprint, abort, current_app, jsonify, send_file, url_for

from ..models import Window
from ..models.visual_scene import VisualScene, VisualSceneOpening
from ..services.domain import quotation_service, share_link_service, visual_feedback_service

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


def _safe_upload(rel_path):
    if not rel_path:
        return None
    base = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.realpath(os.path.join(base, rel_path))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    return full


def _mimetype(path: str) -> str:
    ext = path.rsplit('.', 1)[-1].lower()
    return {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'webp': 'image/webp', 'gif': 'image/gif',
    }.get(ext, 'application/octet-stream')


@public_scene_bp.route('/<token>/visual/scene')
def scene_image(token):
    link = share_link_service.get_active_visualiser_by_token(token)
    if link is None:
        abort(404)

    scene = _scene_for_quotation(link.tenant_id, link.resource_id)
    if scene is None or not scene.rendered_path:
        abort(404)

    full = _safe_upload(scene.rendered_path)
    if not full:
        abort(404)
    return send_file(full, mimetype='image/png')


@public_scene_bp.route('/<token>/visual/scene-photo')
def scene_photo(token):
    """Original home photo for the live visualizer (no login required)."""
    link = share_link_service.get_active_visualiser_by_token(token)
    if link is None:
        abort(404)

    scene = _scene_for_quotation(link.tenant_id, link.resource_id)
    if scene is None or not scene.photo_path:
        abort(404)

    full = _safe_upload(scene.photo_path)
    if not full:
        abort(404)
    return send_file(full, mimetype=_mimetype(full))


# ------------------------------------------------------------------ #
#  Live visualizer data (customer safe, token scoped)
# ------------------------------------------------------------------ #
def _default_design(window):
    return {
        'shape': 'rectangle',
        'unitType': 'window',
        'frame': {'thickness': 68, 'color': getattr(window, 'frame_colour_hex', None) or '#2B2F33'},
        'panes': [{'id': 'p1', 'x': 0, 'y': 0, 'w': 1, 'h': 1,
                   'opening': 'Fixed', 'infill': 'glass', 'glazingBars': []}],
    }


def _parse_design(raw):
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data else None


def _window_design(window, override=None, width=None, height=None):
    design = _parse_design(override) or _parse_design(getattr(window, 'design_json', None))
    if not design:
        design = _default_design(window)
    design = dict(design)
    design['width'] = width or (window.width_mm if window else None) or design.get('width') or 1200
    design['height'] = height or (window.height_mm if window else None) or design.get('height') or 1400
    return design


@public_scene_bp.route('/<token>/visual/live/<int:line_id>')
def live_data(token, line_id):
    link = share_link_service.get_active_visualiser_by_token(token)
    if link is None:
        abort(404)

    q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
    if not q:
        abort(404)

    item = None
    for index, candidate in enumerate(q.line_items):
        if visual_feedback_service.line_key(candidate, index) == line_id:
            item = candidate
            break
    if item is None:
        abort(404)

    try:
        item_window_id = int(item.get('window_id')) if item.get('window_id') is not None else None
    except (TypeError, ValueError):
        item_window_id = None

    project_windows = {
        w.id: w for w in Window.query.filter_by(
            project_id=q.project_id, tenant_id=link.tenant_id).all()
    }

    item_window = project_windows.get(item_window_id) if item_window_id else None
    try:
        item_w = float(item.get('width_mm')) if item.get('width_mm') else None
        item_h = float(item.get('height_mm')) if item.get('height_mm') else None
    except (TypeError, ValueError):
        item_w = item_h = None

    designs = {}
    if item_window is not None:
        designs[str(item_window.id)] = _window_design(
            item_window, item.get('design_json'), item_w, item_h)

    scene = _scene_for_quotation(link.tenant_id, link.resource_id)
    photo_url = None
    photo_w = photo_h = None
    openings = []

    if scene is not None and scene.photo_path and _safe_upload(scene.photo_path):
        photo_url = url_for('public_scene.scene_photo', token=token) + f'?v={scene.version or 1}'
        photo_w, photo_h = scene.photo_width, scene.photo_height
        rows = (VisualSceneOpening.query
                .filter_by(scene_id=scene.id)
                .order_by(VisualSceneOpening.z_index).all())
        for row in rows:
            win = project_windows.get(row.window_id)
            if win is None:
                continue
            corners = row.corners
            if not all(k in corners for k in ('tl', 'tr', 'bl', 'br')):
                continue
            key = str(win.id)
            if key not in designs:
                designs[key] = _window_design(win)
            openings.append({
                'window_id': win.id,
                'corners': corners,
                'opacity': row.opacity,
                'brightness': row.brightness,
                'tint': row.tint_hex,
                'mine': (win.id == item_window_id),
            })

    placed = any(o['mine'] for o in openings)
    if not placed and item_window is None and item_w and item_h:
        # No linked unit: draw a plain unit from the quoted size so the card is never blank.
        designs['0'] = _window_design(None, None, item_w, item_h)

    return jsonify({
        'line_id': line_id,
        'label': item.get('label') or 'Item',
        'window_id': item_window_id if item_window is not None else 0,
        'width_mm': item_w,
        'height_mm': item_h,
        'photo': photo_url,
        'photo_w': photo_w,
        'photo_h': photo_h,
        'openings': openings,
        'designs': designs,
        'placed': placed,
    })
