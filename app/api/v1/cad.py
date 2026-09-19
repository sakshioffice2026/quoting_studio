from flask import Blueprint, jsonify, request, current_app, Response
from flask_login import login_required, current_user

from ...extensions import db
from ...models import Pane
from ...services.cad.engineering_dxf import generate_engineering_dxf
from ...services.cad.orthographic_dxf import generate_orthographic_dxf
from ...services.cad.canonical_geometry import assert_legacy_panes_match, sync_legacy_panes
from ._helpers import _own_window, _validate_or_400
from ...services.domain import design_approval_service

cad_bp = Blueprint('api_v1_cad', __name__)


def _require_design_approved(window):
    """Gate: final engineering/manufacturing output requires an APPROVED
    design_approval on the window's project. Preview formats (svg/pdf
    techdraw, plain dxf) stay open for internal design review."""
    if not design_approval_service.is_project_approved(current_user.tenant_id, window.project_id):
        return jsonify({
            'error': 'Design not approved',
            'message': 'This project\'s design must be approved before manufacturing-grade '
                       'output (DXF/DWG/3D) can be exported.',
        }), 409
    return None


# GET /api/v1/oda-status
@cad_bp.route('/oda-status')
def oda_status():
    try:
        from ...services.cad.dwg_writer import ODA_AVAILABLE
        return jsonify({'available': bool(ODA_AVAILABLE)})
    except Exception:
        return jsonify({'available': False})


# GET /api/v1/windows/<id>/dxf
@cad_bp.route('/windows/<int:window_id>/dxf', methods=['GET'])
@login_required
def export_dxf(window_id):
    fmt = request.args.get('fmt', 'svg').lower()
    if fmt not in ('svg', 'pdf'):
        fmt = 'svg'
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        from ...services.cad.techdraw_export import generate_techdraw
        data = generate_techdraw(window, panes, tenant_id=current_user.tenant_id, fmt=fmt)
        if not data:
            return jsonify({'error': 'Drawing generation failed'}), 500

        mimes = {'svg': 'image/svg+xml', 'pdf': 'application/pdf'}
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.{fmt}'
        current_app.logger.info('Drawing export: window=%d fmt=%s bytes=%d',
                                 window_id, fmt, len(data))
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('export_dxf error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Drawing export failed'}), 500


# GET /api/v1/windows/<id>/drawing/<fmt>
@cad_bp.route('/windows/<int:window_id>/drawing/<fmt>', methods=['GET'])
@login_required
def export_techdraw(window_id, fmt):
    fmt = fmt.lower()
    if fmt not in ('svg', 'pdf'):
        return jsonify({'error': 'Format must be svg or pdf'}), 400
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        from ...services.cad.techdraw_export import generate_techdraw
        data = generate_techdraw(window, panes, tenant_id=current_user.tenant_id, fmt=fmt)
        if not data:
            return jsonify({'error': 'TechDraw generation failed'}), 500

        mimes = {'svg': 'image/svg+xml', 'pdf': 'application/pdf'}
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.{fmt}'
        current_app.logger.info('TechDraw export: window=%d fmt=%s bytes=%d',
                                 window_id, fmt, len(data))
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('export_techdraw error window=%d fmt=%s: %s',
                                      window_id, fmt, exc)
        return jsonify({'error': 'TechDraw drawing export failed'}), 500


# GET /api/v1/windows/<id>/dwg
@cad_bp.route('/windows/<int:window_id>/dwg', methods=['GET'])
@login_required
def export_dwg(window_id):
    try:
        window = _own_window(window_id)
        gate = _require_design_approved(window)
        if gate:
            return gate
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        bad = _validate_or_400(window, panes)
        if bad:
            return bad

        dxf = generate_engineering_dxf(window, panes, tenant_id=current_user.tenant_id)
        if not dxf:
            return jsonify({'error': 'Drawing generation failed'}), 500

        from ...services.cad.dwg_writer import dxf_to_dwg
        dwg = dxf_to_dwg(dxf)

        if dwg:
            fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.dwg'
            current_app.logger.info('DWG export: window=%d bytes=%d', window_id, len(dwg))
            return Response(dwg, mimetype='application/acad',
                            headers={'Content-Disposition': f'attachment; filename={fname}'})

        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.dxf'
        current_app.logger.info('DWG unavailable, serving DXF fallback window=%d', window_id)
        return Response(dxf, mimetype='application/dxf',
                        headers={'Content-Disposition': f'attachment; filename={fname}',
                                 'X-DWG-Fallback': 'DXF (install ODA File Converter for DWG)'})
    except Exception as exc:
        current_app.logger.exception('export_dwg error window=%d: %s', window_id, exc)
        return jsonify({'error': 'DWG export failed'}), 500


# GET /api/v1/windows/<id>/engineering.dxf
@cad_bp.route('/windows/<int:window_id>/engineering.dxf', methods=['GET'])
@login_required
def export_engineering_dxf(window_id):
    try:
        window = _own_window(window_id)
        gate = _require_design_approved(window)
        if gate:
            return gate
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        bad = _validate_or_400(window, panes)
        if bad:
            return bad

        data = generate_engineering_dxf(window, panes, tenant_id=current_user.tenant_id)
        if not data:
            return jsonify({'error': 'Engineering drawing generation failed'}), 500

        fname = f'QS-{window_id}-{(window.label or "unit").replace(" ","_")[:30]}-ENG.dxf'
        current_app.logger.info('Engineering drawing: window=%d bytes=%d', window_id, len(data))
        return Response(data, mimetype='application/dxf',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('engineering drawing error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Engineering drawing generation failed'}), 500


# GET /api/v1/windows/<id>/orthographic.dxf
@cad_bp.route('/windows/<int:window_id>/orthographic.dxf', methods=['GET'])
@login_required
def export_orthographic_dxf(window_id):
    try:
        window = _own_window(window_id)
        gate = _require_design_approved(window)
        if gate:
            return gate
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        bad = _validate_or_400(window, panes)
        if bad:
            return bad

        data = generate_orthographic_dxf(window, panes, tenant_id=current_user.tenant_id)
        if not data:
            return jsonify({'error': 'Orthographic drawing generation failed'}), 500

        fname = f'QS-{window_id}-{(window.label or "unit").replace(" ","_")[:30]}-ORTHO.dxf'
        current_app.logger.info('Orthographic drawing: window=%d bytes=%d', window_id, len(data))
        return Response(data, mimetype='application/dxf',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('orthographic drawing error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Orthographic drawing generation failed'}), 500


# GET /api/v1/windows/<id>/draft-views.fcstd
@cad_bp.route('/windows/<int:window_id>/draft-views.fcstd', methods=['GET'])
@login_required
def export_draft_views_fcstd(window_id):
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        bad = _validate_or_400(window, panes)
        if bad:
            return bad

        from ...services.cad.model3d_freecad import generate_3d_freecad
        data = generate_3d_freecad(window, panes, tenant_id=current_user.tenant_id, fmt='fcstd')
        if not data:
            return jsonify({'error': 'Draft views generation failed'}), 500

        fname = f'QS-{window_id}-{(window.label or "unit").replace(" ","_")[:30]}-DRAFT.fcstd'
        current_app.logger.info('Draft views document: window=%d bytes=%d', window_id, len(data))
        return Response(data, mimetype='application/octet-stream',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('draft views drawing error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Draft views generation failed'}), 500


# GET /api/v1/windows/<id>/techdraw-views.fcstd
@cad_bp.route('/windows/<int:window_id>/techdraw-views.fcstd', methods=['GET'])
@login_required
def export_techdraw_views_fcstd(window_id):
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        bad = _validate_or_400(window, panes)
        if bad:
            return bad

        from ...services.cad.model3d_freecad import generate_3d_freecad
        data = generate_3d_freecad(window, panes, tenant_id=current_user.tenant_id, fmt='techdraw')
        if not data:
            return jsonify({'error': 'TechDraw views generation failed'}), 500

        fname = f'QS-{window_id}-{(window.label or "unit").replace(" ","_")[:30]}-TECHDRAW.fcstd'
        current_app.logger.info('TechDraw views document: window=%d bytes=%d', window_id, len(data))
        return Response(data, mimetype='application/octet-stream',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('techdraw views drawing error window=%d: %s', window_id, exc)
        return jsonify({'error': 'TechDraw views generation failed'}), 500


# GET /api/v1/windows/<id>/3d/<fmt>
@cad_bp.route('/windows/<int:window_id>/3d/<fmt>', methods=['GET'])
@login_required
def export_3d(window_id, fmt):
    fmt = fmt.lower()
    if fmt not in ('step', 'stl', 'glb', 'dxf'):
        return jsonify({'error': 'Format must be step, stl, glb or dxf'}), 400

    method = request.args.get('method', 'auto')
    if method not in ('auto', 'assembly', 'freecad', 'profile', 'extrude', 'sweep'):
        method = 'auto'

    default_axis = 'zup' if fmt == 'step' else 'y'
    z_up = request.args.get('axis', default_axis).lower() == 'zup'

    try:
        window = _own_window(window_id)
        gate = _require_design_approved(window)
        if gate:
            return gate
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()

        if fmt == 'dxf':
            from ...services.cad.model3d import generate_multiview_dxf
            data = generate_multiview_dxf(window, panes, tenant_id=current_user.tenant_id)
        else:
            from ...services.cad.model3d import generate_3d
            data = generate_3d(window, panes, tenant_id=current_user.tenant_id,
                               fmt=fmt, method=method, z_up=z_up)

        if not data:
            return jsonify({'error': '3D generation failed — cadquery may not be installed'}), 500

        mimes = {'step': 'application/step', 'stl': 'model/stl',
                 'glb': 'model/gltf-binary', 'dxf': 'application/dxf'}
        ext   = {'step': 'step', 'stl': 'stl', 'glb': 'glb', 'dxf': 'dxf'}[fmt]
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.{ext}'
        current_app.logger.info('3D export: window=%d fmt=%s method=%s bytes=%d',
                                 window_id, fmt, method, len(data))
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('export_3d error window=%d fmt=%s: %s', window_id, fmt, exc)
        return jsonify({'error': '3D export failed'}), 500
