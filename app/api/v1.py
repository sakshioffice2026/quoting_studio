from flask import Blueprint, jsonify, request, abort, current_app, Response
from flask_login import login_required, current_user

import json

from ..extensions import db
from ..models import Window, Pane
from ..services.pricing import calculate_price
from ..services.engineering_dxf import generate_engineering_dxf
from ..services.canonical_geometry import (
    assert_legacy_panes_match,
    sync_legacy_panes,
)

api_v1_bp = Blueprint('api_v1', __name__)


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>
# ------------------------------------------------------------------ #
@api_v1_bp.route('/oda-status')
def oda_status():
    """Return whether ODA File Converter is available on this server."""
    try:
        from ..services.dwg_writer import ODA_AVAILABLE
        return jsonify({'available': bool(ODA_AVAILABLE)})
    except Exception:
        return jsonify({'available': False})


@api_v1_bp.route('/windows/<int:window_id>', methods=['GET'])
@login_required
def get_window(window_id):
    try:
        window = _own_window(window_id)
        current_app.logger.debug('API get_window: id=%d', window_id)
        return jsonify(window.to_dict())
    except Exception as exc:
        current_app.logger.exception('API get_window error id=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to load window'}), 500


# ------------------------------------------------------------------ #
#  POST /api/v1/windows/<id>/panes
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/panes', methods=['POST'])
@login_required
def save_panes(window_id):
    try:
        window = _own_window(window_id)
        data   = request.get_json(force=True)

        if not data:
            current_app.logger.warning('save_panes: empty payload window_id=%d', window_id)
            return jsonify({'error': 'Empty request body'}), 400

        # update window-level fields if provided
        if 'width'          in data: window.width_mm          = int(data['width'])
        if 'height'         in data: window.height_mm         = int(data['height'])
        if 'material'       in data: window.material          = data['material']
        if 'frameColor'     in data: window.frame_colour_hex  = data['frameColor']
        if 'frameColorName' in data: window.frame_colour_name = data['frameColorName']

        cells = data.get('cells', [])
        if not isinstance(cells, list):
            return jsonify({'error': 'cells must be an array'}), 400

        # design_json is authoritative. Keep the legacy Pane table as a
        # deterministic compatibility projection of the posted design.
        design = data.get('design_json')
        if design is None:
            design = json.dumps({'panes': cells})
        elif isinstance(design, dict):
            design = json.dumps(design)
        window.design_json = design
        sync_legacy_panes(window, Pane, db)

        db.session.commit()
        current_app.logger.info('save_panes: window=%d cells=%d', window_id, len(cells))
        return jsonify({'status': 'ok', 'cells_saved': len(cells)})

    except ValueError as exc:
        db.session.rollback()
        current_app.logger.warning('save_panes bad data window=%d: %s', window_id, exc)
        return jsonify({'error': f'Invalid data: {exc}'}), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_panes error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save panes'}), 500


# ------------------------------------------------------------------ #
#  POST /api/v1/windows/<id>/price
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/price', methods=['POST'])
@login_required
def get_price(window_id):
    try:
        window = _own_window(window_id)
        data   = request.get_json(force=True) or {}

        # transient pane objects from posted data — no DB round-trip needed
        class _P:
            def __init__(self, opener, glazing, w=1.0, h=1.0):
                self.opener_type  = opener
                self.glazing_type = glazing
                self.w_norm       = w
                self.h_norm       = h

        cells = data.get('cells', None)
        if cells is not None:
            panes = [_P(c.get('opener', 'Fixed light'), c.get('glazing', 'Double, Low-E'),
                        float(c.get('w', 1.0)), float(c.get('h', 1.0)))
                     for c in cells]
        else:
            panes = window.panes.all()

        # apply transient overrides for live preview
        if 'material' in data: window.material  = data['material']
        if 'width'    in data: window.width_mm  = int(data['width'])
        if 'height'   in data: window.height_mm = int(data['height'])

        # accept full design for hardware/extras/bar pricing
        design = data.get('design') or None
        if design is None and (data.get('hardware') or data.get('extras') or data.get('glazingBars') is not None):
            design = {
                'hardware': data.get('hardware', {}),
                'extras':   data.get('extras', {}),
                'panes':    [{'glazingBars': c.get('glazingBars', [])} for c in (cells or [])],
            }
        result = calculate_price(window, panes, current_user.tenant_id, design=design)
        current_app.logger.debug('price: window=%d total=%.2f', window_id, result['total'])
        return jsonify(result)

    except Exception as exc:
        current_app.logger.exception('get_price error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Pricing calculation failed'}), 500


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>/dxf   — 2D drawing (now served via FreeCAD
#  TechDraw: STEP -> Import.insert() -> DrawViewPart/DrawViewSection ->
#  SVG). ezdxf generator retired for this route; ?fmt=pdf for PDF.
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/dxf', methods=['GET'])
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

        from ..services.techdraw_export import generate_techdraw
        data = generate_techdraw(window, panes, tenant_id=current_user.tenant_id, fmt=fmt)
        if not data:
            return jsonify({'error': 'Drawing generation failed'}), 500

        mimes = {'svg': 'image/svg+xml', 'pdf': 'application/pdf'}
        current_app.logger.info('Drawing export: window=%d fmt=%s bytes=%d',
                                 window_id, fmt, len(data))
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.{fmt}'
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('export_dxf error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Drawing export failed'}), 500


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>/drawing/<fmt>   — FreeCAD TechDraw 2D drawing
#  (replaces DXF export: STEP -> Import.insert() -> TechDraw.DrawViewPart
#   -> SVG/PDF). fmt: svg | pdf
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/drawing/<fmt>', methods=['GET'])
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

        from ..services.techdraw_export import generate_techdraw
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


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>/dwg   — true DWG (needs ODA converter)
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/dwg', methods=['GET'])
@login_required
def export_dwg(window_id):
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()
        dxf    = generate_engineering_dxf(window, panes, tenant_id=current_user.tenant_id)
        if not dxf:
            return jsonify({'error': 'Drawing generation failed'}), 500

        from ..services.dwg_writer import dxf_to_dwg
        dwg = dxf_to_dwg(dxf)

        if dwg:
            fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.dwg'
            current_app.logger.info('DWG export: window=%d bytes=%d', window_id, len(dwg))
            return Response(dwg, mimetype='application/acad',
                            headers={'Content-Disposition': f'attachment; filename={fname}'})

        # ODA not available — fall back to DXF with a note in the header
        current_app.logger.info('DWG unavailable, serving DXF fallback window=%d', window_id)
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.dxf'
        return Response(dxf, mimetype='application/dxf',
                        headers={'Content-Disposition': f'attachment; filename={fname}',
                                 'X-DWG-Fallback': 'DXF (install ODA File Converter for DWG)'})
    except Exception as exc:
        current_app.logger.exception('export_dwg error window=%d: %s', window_id, exc)
        return jsonify({'error': 'DWG export failed'}), 500


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>/3d/<fmt>   — 3D model (step | stl | glb)
#  Query: ?method=extrude|sweep  (default extrude)
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/engineering.dxf', methods=['GET'])
@login_required
def export_engineering_dxf(window_id):
    """Engineering drawing sheet (elevation + section + dimensions), now
    generated via FreeCAD TechDraw off the real STEP solid instead of the
    ezdxf sketch. ?fmt=pdf for PDF, default svg."""
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

        from ..services.techdraw_export import generate_techdraw
        data = generate_techdraw(window, panes,
                                 tenant_id=current_user.tenant_id, fmt=fmt)
        mimes = {'svg': 'image/svg+xml', 'pdf': 'application/pdf'}
        fname = f'QS-{window_id}-{(window.label or "unit").replace(" ","_")[:30]}-ENG.{fmt}'
        current_app.logger.info('Engineering drawing: window=%d fmt=%s bytes=%d',
                                window_id, fmt, len(data))
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition':
                                 f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('engineering drawing error window=%d: %s',
                                     window_id, exc)
        return jsonify({'error': 'Engineering drawing generation failed'}), 500


# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/3d/<fmt>', methods=['GET'])
@login_required
def export_3d(window_id, fmt):
    fmt = fmt.lower()
    if fmt not in ('step', 'stl', 'glb'):
        return jsonify({'error': 'Format must be step, stl or glb'}), 400
    method = request.args.get('method', 'auto')
    if method not in ('auto', 'assembly', 'freecad', 'profile', 'extrude', 'sweep'):
        method = 'auto'
    z_up = request.args.get('axis', 'y').lower() == 'zup'
    try:
        window = _own_window(window_id)
        panes  = window.panes.all()
        try:
            assert_legacy_panes_match(window, panes)
        except ValueError:
            sync_legacy_panes(window, Pane, db)
            db.session.commit()
            panes = window.panes.all()
        from ..services.model3d import generate_3d
        data = generate_3d(window, panes, tenant_id=current_user.tenant_id,
                            fmt=fmt, method=method, z_up=z_up)
        if not data:
            return jsonify({'error': '3D generation failed — cadquery may not be installed'}), 500

        mimes = {'step':'application/step', 'stl':'model/stl', 'glb':'model/gltf-binary'}
        ext   = {'step':'step', 'stl':'stl', 'glb':'glb'}[fmt]
        fname = f'QS-{window_id}-{window.label.replace(" ","_")[:30]}.{ext}'
        current_app.logger.info('3D export: window=%d fmt=%s method=%s bytes=%d',
                                 window_id, fmt, method, len(data))
        return Response(data, mimetype=mimes[fmt],
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as exc:
        current_app.logger.exception('export_3d error window=%d fmt=%s: %s',
                                      window_id, fmt, exc)
        return jsonify({'error': '3D export failed'}), 500


# ------------------------------------------------------------------ #
#  POST /api/v1/windows/<id>/design   — save SVG-engine design
#  Body: { design_json, width, height, material, frameColor,
#          frameColorName, cells:[{x,y,w,h,opener,glazing}] }
#  Saves full design_json to the window AND syncs the legacy panes table
#  so pricing / quotes / DXF / 3D (which read panes) stay consistent.
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/design', methods=['POST'])
@login_required
def save_design(window_id):
    try:
        window = _own_window(window_id)
        data   = request.get_json(force=True) or {}

        # 1) store the full parametric model. If cells are supplied by the
        # designer, they are folded into design_json before any compatibility
        # rows are rebuilt; design_json remains the only source of truth.
        design = data.get('design_json')
        if isinstance(design, str):
            try:
                design_obj = json.loads(design)
            except ValueError as exc:
                return jsonify({'error': f'Invalid design_json: {exc}'}), 400
        elif isinstance(design, dict):
            design_obj = dict(design)
        else:
            design_obj = {}
        if 'cells' in data:
            design_obj['panes'] = data['cells']
        window.design_json = json.dumps(design_obj)

        # 2) update the window's summary fields
        if 'width'  in data: window.width_mm  = int(data['width'])
        if 'height' in data: window.height_mm = int(data['height'])
        if 'material' in data: window.material = data['material']
        if 'frameColor' in data:
            window.frame_colour_hex = data['frameColor']
        if 'frameColorName' in data:
            window.frame_colour_name = data['frameColorName']
        # profile system link (which named DXF-profile set builds the 3D frame)
        if 'profileSystemId' in data:
            val = data['profileSystemId']
            window.profile_system_id = int(val) if val else None

        # 3) rebuild the legacy panes table only from design_json
        sync_legacy_panes(window, Pane, db)

        db.session.commit()
        current_app.logger.info('Design saved: window=%d panes=%d',
                                 window_id, len(design_obj.get('panes') or []))
        return jsonify({'ok': True, 'window_id': window_id})

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save_design error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Design save failed'}), 500


# ------------------------------------------------------------------ #
#  Internal
# ------------------------------------------------------------------ #
def _own_window(window_id: int) -> Window:
    w = Window.query.filter_by(
        id=window_id, tenant_id=current_user.tenant_id
    ).first()
    if w is None:
        current_app.logger.warning('Window not found or access denied: id=%d tenant=%d',
                                    window_id, current_user.tenant_id)
        abort(404)
    return w


# ================================================================
#  VISUALISER ENDPOINTS  (Phase 6)
# ================================================================
import base64, uuid, os
from ..models import Visualisation

# ------------------------------------------------------------------ #
#  POST /api/v1/windows/<id>/render
#  Body: { image: "data:image/png;base64,..." }
#  Saves the Three.js canvas snapshot as the window render texture.
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/render', methods=['POST'])
@login_required
def save_render(window_id):
    try:
        window = _own_window(window_id)
        data   = request.get_json(force=True) or {}
        b64    = data.get('image', '')

        if not b64:
            return jsonify({'error': 'No image data provided'}), 400

        # strip data-URI prefix if present
        if ',' in b64:
            b64 = b64.split(',', 1)[1]

        try:
            img_bytes = base64.b64decode(b64)
        except Exception as exc:
            current_app.logger.warning('save_render: invalid base64 window=%d: %s', window_id, exc)
            return jsonify({'error': 'Invalid base64 image data'}), 400

        render_dir  = os.path.join(current_app.config['UPLOAD_FOLDER'], 'renders')
        os.makedirs(render_dir, exist_ok=True)
        filename    = f'window-{window_id}.png'
        render_path = os.path.join(render_dir, filename)

        with open(render_path, 'wb') as f:
            f.write(img_bytes)

        render_url = f'/uploads/renders/{filename}'

        # persist the render path on the latest Visualisation row (create if none)
        # so the visualiser / quote can load the exact file without guessing.
        from ..models import Visualisation
        vis = (Visualisation.query.filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc()).first())
        if vis is None:
            vis = Visualisation(window_id=window_id)
            db.session.add(vis)
        vis.rendered_path = f'renders/{filename}'
        db.session.commit()

        current_app.logger.info('save_render: window=%d saved %d bytes -> %s',
                                 window_id, len(img_bytes), render_path)
        return jsonify({'status': 'ok', 'render_url': render_url})

    except Exception as exc:
        current_app.logger.exception('save_render error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save render'}), 500


# ------------------------------------------------------------------ #
#  POST /api/v1/windows/<id>/photo
#  Multipart upload — saves house photo, links to visualisation record.
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/photo', methods=['POST'])
@login_required
def upload_photo(window_id):
    try:
        window = _own_window(window_id)

        if 'photo' not in request.files:
            return jsonify({'error': 'No photo file in request'}), 400

        file = request.files['photo']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        # validate extension
        allowed = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed:
            return jsonify({'error': f'File type .{ext} not allowed'}), 400

        photo_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'photos')
        os.makedirs(photo_dir, exist_ok=True)
        filename   = f'window-{window_id}-{uuid.uuid4().hex[:8]}.{ext}'
        photo_path = os.path.join(photo_dir, filename)
        file.save(photo_path)

        # upsert visualisation record with photo path
        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        from ..extensions import db as _db
        if not vis:
            vis = Visualisation(window_id=window_id)
            _db.session.add(vis)
        vis.photo_path = f'photos/{filename}'
        _db.session.commit()

        photo_url = f'/uploads/photos/{filename}'
        current_app.logger.info('upload_photo: window=%d → %s', window_id, photo_path)
        return jsonify({'status': 'ok', 'photo_url': photo_url, 'vis_id': vis.id})

    except Exception as exc:
        current_app.logger.exception('upload_photo error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Photo upload failed'}), 500


# ------------------------------------------------------------------ #
#  GET  /api/v1/windows/<id>/visualisation  — load saved state
#  POST /api/v1/windows/<id>/visualisation  — save corners + settings
# ------------------------------------------------------------------ #
@api_v1_bp.route('/windows/<int:window_id>/visualisation', methods=['GET'])
@login_required
def get_visualisation(window_id):
    try:
        _own_window(window_id)
        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if not vis:
            return jsonify({'exists': False})

        # find the most recently saved render for this window
        import glob, os as _os
        render_dir = _os.path.join(current_app.config.get('UPLOAD_FOLDER','uploads'), 'renders')
        pattern    = _os.path.join(render_dir, f'window-{window_id}-*.png')
        matches    = sorted(glob.glob(pattern), key=_os.path.getmtime, reverse=True)
        render_url = (f'/uploads/renders/{_os.path.basename(matches[0])}'
                      if matches else None)
        photo_url  = f'/uploads/{vis.photo_path}' if vis.photo_path else None

        return jsonify({
            'exists':     True,
            'id':         vis.id,
            'render_url': render_url,
            'photo_url':  photo_url,
            'opacity':    vis.opacity,
            'brightness': vis.brightness,
            'corners': {
                'tl': [vis.corner_tl_x, vis.corner_tl_y],
                'tr': [vis.corner_tr_x, vis.corner_tr_y],
                'bl': [vis.corner_bl_x, vis.corner_bl_y],
                'br': [vis.corner_br_x, vis.corner_br_y],
            } if vis.corner_tl_x is not None else None,
        })
    except Exception as exc:
        current_app.logger.exception('get_visualisation error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to load visualisation'}), 500


@api_v1_bp.route('/windows/<int:window_id>/visualisation', methods=['POST'])
@login_required
def save_visualisation(window_id):
    try:
        _own_window(window_id)
        data = request.get_json(force=True) or {}

        from ..extensions import db as _db
        vis = (Visualisation.query
               .filter_by(window_id=window_id)
               .order_by(Visualisation.created_at.desc())
               .first())
        if not vis:
            vis = Visualisation(window_id=window_id)
            _db.session.add(vis)

        corners = data.get('corners', {})
        if corners:
            tl = corners.get('tl', [None, None])
            tr = corners.get('tr', [None, None])
            bl = corners.get('bl', [None, None])
            br = corners.get('br', [None, None])
            vis.corner_tl_x = tl[0]; vis.corner_tl_y = tl[1]
            vis.corner_tr_x = tr[0]; vis.corner_tr_y = tr[1]
            vis.corner_bl_x = bl[0]; vis.corner_bl_y = bl[1]
            vis.corner_br_x = br[0]; vis.corner_br_y = br[1]

        if 'opacity'    in data: vis.opacity    = float(data['opacity'])
        if 'brightness' in data: vis.brightness = float(data['brightness'])

        _db.session.commit()
        current_app.logger.debug('save_visualisation: window=%d vis=%d', window_id, vis.id)
        return jsonify({'status': 'ok', 'vis_id': vis.id})

    except Exception as exc:
        current_app.logger.exception('save_visualisation error window=%d: %s', window_id, exc)
        return jsonify({'error': 'Failed to save visualisation'}), 500