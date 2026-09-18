from flask import abort, jsonify, current_app
from flask_login import current_user

from ...models import Window
from ...services.cad_geometry_validator import validate_before_export


def _own_window(window_id: int) -> Window:
    w = Window.query.filter_by(
        id=window_id, tenant_id=current_user.tenant_id
    ).first()
    if w is None:
        current_app.logger.warning(
            'Window not found or access denied: id=%d tenant=%d',
            window_id, current_user.tenant_id
        )
        abort(404)
    return w


def _profile_dict_for_validation(window) -> dict:
    material = getattr(window, 'material', 'Aluminium')
    prof = {'bar': 58.0, 'depth': 70.0, 'wall': 4.0}
    try:
        from ...models.cad_profile import CadProfile
        p = (
            CadProfile.query
            .filter_by(tenant_id=current_user.tenant_id, material=material,
                       is_active=True, is_default=True).first()
            or CadProfile.query
            .filter_by(tenant_id=current_user.tenant_id, is_active=True).first()
        )
        if p:
            prof = {
                'bar':   float(p.bar_width_mm),
                'depth': float(p.depth_mm),
                'wall':  float(p.wall_thickness_mm),
            }
    except Exception as exc:
        current_app.logger.warning('profile lookup for validation failed: %s', exc)
    return prof


def _validate_or_400(window, panes):
    profile = _profile_dict_for_validation(window)
    result  = validate_before_export(window, panes, profile)
    if result.has_errors():
        current_app.logger.warning(
            'Export blocked by validation window=%d errors=%d: %s',
            window.id, result.error_count(),
            [i.message for i in result.issues if i.severity.value == 'error']
        )
        return jsonify(result.to_dict()), 400
    if result.has_warnings():
        current_app.logger.info(
            'Export proceeding with warnings window=%d: %s',
            window.id,
            [i.message for i in result.issues if i.severity.value == 'warning']
        )
    return None
