from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app, jsonify
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Project, ProjectStatus, Window, Pane

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')


# ------------------------------------------------------------------ #
#  New project
# ------------------------------------------------------------------ #
@projects_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        address       = request.form.get('address', '').strip()
        notes         = request.form.get('notes', '').strip()

        if not customer_name:
            flash('Customer name is required.', 'error')
            return render_template('projects/new.html')

        try:
            project = Project(
                tenant_id=current_user.tenant_id,
                created_by=current_user.id,
                customer_name=customer_name,
                address=address or None,
                notes=notes or None,
            )
            db.session.add(project)
            db.session.commit()

            current_app.logger.info('Project created: id=%d customer=%s tenant=%d',
                                     project.id, customer_name, current_user.tenant_id)
            flash('Project created. Choose the first unit to add.', 'success')
            # New flow: land on the unit chooser (window/door → template) rather
            # than defaulting straight to a blank window in the editor.
            return redirect(url_for('projects.choose_unit', project_id=project.id))

        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Failed to create project for tenant=%d: %s',
                                          current_user.tenant_id, exc)
            flash('Failed to create project. Please try again.', 'error')

    return render_template('projects/new.html')


# ------------------------------------------------------------------ #
#  Project detail
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>')
@login_required
def detail(project_id):
    try:
        from ..models import Quote
        from sqlalchemy import desc
        project = _own_project(project_id)
        windows = project.windows.all()
        quotes  = (Quote.query
                   .filter_by(project_id=project_id, tenant_id=current_user.tenant_id)
                   .order_by(desc(Quote.created_at))
                   .all())
        current_app.logger.debug('Project detail: id=%d tenant=%d windows=%d quotes=%d',
                                  project_id, current_user.tenant_id, len(windows), len(quotes))
        return render_template('projects/detail.html',
                               project=project, windows=windows, quotes=quotes)
    except Exception as exc:
        current_app.logger.exception('Error loading project detail id=%d: %s', project_id, exc)
        flash('Could not load project.', 'error')
        return redirect(url_for('dashboard.index'))


# ------------------------------------------------------------------ #
#  Facade View — all units composited on a building elevation
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/facade')
@login_required
def facade(project_id):
    try:
        import json
        project = _own_project(project_id)
        windows = project.windows.order_by(Window.sequence_order).all()
        # build a lightweight JSON list of units with their design for the client
        units = []
        for w in windows:
            design = None
            try:
                if getattr(w, 'design_json', None):
                    design = json.loads(w.design_json)
            except Exception:
                design = None
            if not design:
                design = {
                    'width': w.width_mm, 'height': w.height_mm,
                    'shape': 'rectangle', 'unitType': 'window',
                    'frame': {'thickness': 58, 'color': w.frame_colour_hex},
                    'panes': [{'id':'p1','x':0,'y':0,'w':1,'h':1,
                               'opening':'Fixed','glazing':'Double, Low-E','glazingBars':[]}],
                }
            units.append({
                'id': w.id, 'label': w.label,
                'width': w.width_mm, 'height': w.height_mm,
                'design': design,
            })
        facade_state = None
        try:
            if getattr(project, 'facade_json', None):
                facade_state = json.loads(project.facade_json)
        except Exception:
            facade_state = None
        return render_template('facade.html',
                               project=project, units=units,
                               facade_state=json.dumps(facade_state) if facade_state else 'null')
    except Exception as exc:
        current_app.logger.exception('Facade view error id=%d: %s', project_id, exc)
        flash('Could not load facade view.', 'error')
        return redirect(url_for('projects.detail', project_id=project_id))


@projects_bp.route('/<int:project_id>/facade/save', methods=['POST'])
@login_required
def facade_save(project_id):
    try:
        import json
        project = _own_project(project_id)
        data = request.get_json(force=True) or {}
        project.facade_json = json.dumps(data.get('facade', {}))
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Facade save error id=%d: %s', project_id, exc)
        return jsonify({'error': 'Save failed'}), 500


# ------------------------------------------------------------------ #
#  Edit project metadata
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(project_id):
    try:
        project = _own_project(project_id)

        if request.method == 'POST':
            project.customer_name = request.form.get('customer_name', '').strip() or project.customer_name
            project.address       = request.form.get('address', '').strip() or None
            project.notes         = request.form.get('notes', '').strip() or None
            status                = request.form.get('status')
            if status in ProjectStatus.ALL:
                project.status = status
            project.updated_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info('Project updated: id=%d', project_id)
            flash('Project updated.', 'success')
            return redirect(url_for('projects.detail', project_id=project.id))

        return render_template('projects/edit.html', project=project,
                               statuses=ProjectStatus.ALL, labels=ProjectStatus.LABELS)

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Error editing project id=%d: %s', project_id, exc)
        flash('Could not update project.', 'error')
        return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
#  Delete project
# ------------------------------------------------------------------ #
#  Delete a single window / door from a project
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/windows/<int:window_id>/delete', methods=['POST'])
@login_required
def delete_window(project_id, window_id):
    project = _own_project(project_id)
    window  = Window.query.filter_by(
        id=window_id, project_id=project_id,
        tenant_id=current_user.tenant_id).first_or_404()
    label = window.label or f'Window {window_id}'
    try:
        db.session.delete(window)
        db.session.commit()
        flash(f'"{label}" deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Error deleting window id=%d: %s', window_id, exc)
        flash('Could not delete window.', 'error')
    return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/delete', methods=['POST'])
@login_required
def delete(project_id):
    try:
        project = _own_project(project_id)
        db.session.delete(project)
        db.session.commit()
        current_app.logger.info('Project deleted: id=%d tenant=%d', project_id, current_user.tenant_id)
        flash('Project deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Error deleting project id=%d: %s', project_id, exc)
        flash('Could not delete project.', 'error')
    return redirect(url_for('dashboard.index'))


# ------------------------------------------------------------------ #
#  Add window/door to project — chooser flow
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/add', methods=['GET'])
@login_required
def choose_unit(project_id):
    """Step 1/2 page: pick window vs door, then a template."""
    project = _own_project(project_id)
    return render_template('projects/choose_unit.html', project=project)


# Template pane layouts (server mirror of drawing-engine.js TEMPLATES).
# Only the fields needed to seed design_json: panes + shape + door + unit.
_TPL = {
    # windows
    'single':        {'unit':'window','shape':'rectangle','panes':[(0,0,1,1,'Fixed',None)]},
    'double':        {'unit':'window','shape':'rectangle','panes':[(0,0,.5,1,'Fixed',None),(.5,0,.5,1,'Fixed',None)]},
    'triple':        {'unit':'window','shape':'rectangle','panes':[(0,0,.34,1,'Fixed',None),(.34,0,.33,1,'Fixed',None),(.67,0,.33,1,'Fixed',None)]},
    'quad':          {'unit':'window','shape':'rectangle','panes':[(0,0,.25,1,'Fixed',None),(.25,0,.25,1,'Fixed',None),(.5,0,.25,1,'Fixed',None),(.75,0,.25,1,'Fixed',None)]},
    'casement2':     {'unit':'window','shape':'rectangle','panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'casement3':     {'unit':'window','shape':'rectangle','panes':[(0,0,.28,1,'Left Open',None),(.28,0,.44,1,'Fixed',None),(.72,0,.28,1,'Right Open',None)]},
    'casementTopVent':{'unit':'window','shape':'rectangle','panes':[(0,0,.5,.28,'Top Hung',None),(.5,0,.5,.28,'Top Hung',None),(0,.28,.5,.72,'Left Open',None),(.5,.28,.5,.72,'Right Open',None)]},
    'sash':          {'unit':'window','shape':'rectangle','panes':[(0,0,1,.5,'Sliding',None),(0,.5,1,.5,'Sliding',None)]},
    'sash2over2':    {'unit':'window','shape':'rectangle','panes':[(0,0,1,.5,'Sliding',{'v':1}),(0,.5,1,.5,'Sliding',{'v':1})]},
    'sash6over6':    {'unit':'window','shape':'rectangle','panes':[(0,0,1,.5,'Sliding',{'v':2,'h':1}),(0,.5,1,.5,'Sliding',{'v':2,'h':1})]},
    'sashMarginal':  {'unit':'window','shape':'rectangle','panes':[(0,0,1,.5,'Sliding',{'v':1}),(0,.5,1,.5,'Sliding',{'v':1})]},
    'twoOverTwo':    {'unit':'window','shape':'rectangle','panes':[(0,0,.5,.5,'Fixed',None),(.5,0,.5,.5,'Fixed',None),(0,.5,.5,.5,'Fixed',None),(.5,.5,.5,.5,'Fixed',None)]},
    'georgian3x2':   {'unit':'window','shape':'rectangle','panes':[(0,0,1,1,'Fixed',{'v':2,'h':1})]},
    'georgian4x3':   {'unit':'window','shape':'rectangle','panes':[(0,0,1,1,'Fixed',{'v':3,'h':2})]},
    'cottage':       {'unit':'window','shape':'rectangle','panes':[(0,0,.34,.32,'Fixed',None),(.34,0,.33,.32,'Fixed',None),(.67,0,.33,.32,'Fixed',None),(0,.32,.34,.68,'Fixed',None),(.34,.32,.33,.68,'Fixed',None),(.67,.32,.33,.68,'Fixed',None)]},
    'threeOverOne':  {'unit':'window','shape':'rectangle','panes':[(0,0,.34,.4,'Fixed',None),(.34,0,.33,.4,'Fixed',None),(.67,0,.33,.4,'Fixed',None),(0,.4,1,.6,'Fixed',None)]},
    'bay3':          {'unit':'window','shape':'rectangle','panes':[(0,0,.26,1,'Left Open',None),(.26,0,.48,1,'Fixed',None),(.74,0,.26,1,'Right Open',None)]},
    'bay5':          {'unit':'window','shape':'rectangle','panes':[(0,0,.2,1,'Fixed',None),(.2,0,.2,1,'Fixed',None),(.4,0,.2,1,'Fixed',None),(.6,0,.2,1,'Fixed',None),(.8,0,.2,1,'Fixed',None)]},
    'archedSingle':  {'unit':'window','shape':'arched','panes':[(0,0,1,1,'Fixed',None)]},
    'archedDouble':  {'unit':'window','shape':'arched','panes':[(0,0,.5,1,'Fixed',None),(.5,0,.5,1,'Fixed',None)]},
    'gothic':        {'unit':'window','shape':'gothic','panes':[(0,0,1,1,'Fixed',None)]},
    'circular':      {'unit':'window','shape':'circular','panes':[(0,0,1,1,'Fixed',None)]},
    # doors
    'doorSingle':    {'unit':'door','shape':'rectangle','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',None)]},
    'doorHalfGlazed':{'unit':'door','shape':'rectangle','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,.5,'Fixed',None),(0,.5,1,.5,'Right Open',None)]},
    'doorFullGlazed':{'unit':'door','shape':'rectangle','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',None)]},
    'doorGeorgian':  {'unit':'door','shape':'rectangle','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',{'v':1,'h':2})]},
    'doorDouble':    {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'doorFrench':    {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'doorFrenchGeorgian':{'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',{'v':1,'h':3}),(.5,0,.5,1,'Right Open',{'v':1,'h':3})]},
    'doorSideL':     {'unit':'door','shape':'rectangle','door':{'dtype':'sl','leafCount':1,'slL':300,'slR':0,'flH':0},'panes':[(0,0,.25,1,'Fixed',None),(.25,0,.75,1,'Right Open',None)]},
    'doorSideR':     {'unit':'door','shape':'rectangle','door':{'dtype':'sr','leafCount':1,'slL':0,'slR':300,'flH':0},'panes':[(0,0,.75,1,'Left Open',None),(.75,0,.25,1,'Fixed',None)]},
    'doorSideBoth':  {'unit':'door','shape':'rectangle','door':{'dtype':'full','leafCount':1,'slL':250,'slR':250,'flH':0},'panes':[(0,0,.22,1,'Fixed',None),(.22,0,.56,1,'Right Open',None),(.78,0,.22,1,'Fixed',None)]},
    'doorFanlight':  {'unit':'door','shape':'rectangle','door':{'dtype':'fan','leafCount':1,'slL':0,'slR':0,'flH':400},'panes':[(0,0,1,.25,'Fixed',None),(0,.25,1,.75,'Right Open',None)]},
    'doorFullSet':   {'unit':'door','shape':'rectangle','door':{'dtype':'full','leafCount':2,'slL':250,'slR':250,'flH':350},'panes':[(0,0,1,.22,'Fixed',None),(0,.22,.22,.78,'Fixed',None),(.22,.22,.28,.78,'Left Open',None),(.5,.22,.28,.78,'Right Open',None),(.78,.22,.22,.78,'Fixed',None)]},
    'bifold2':       {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'bifold3':       {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':3,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.334,1,'Left Open',None),(.334,0,.333,1,'Left Open',None),(.667,0,.333,1,'Right Open',None)]},
    'bifold4':       {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':4,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.25,1,'Left Open',None),(.25,0,.25,1,'Left Open',None),(.5,0,.25,1,'Right Open',None),(.75,0,.25,1,'Right Open',None)]},
    'bifold5':       {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':5,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.2,1,'Left Open',None),(.2,0,.2,1,'Left Open',None),(.4,0,.2,1,'Left Open',None),(.6,0,.2,1,'Right Open',None),(.8,0,.2,1,'Right Open',None)]},
    'bifold6':       {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':6,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.1667,1,'Left Open',None),(.1667,0,.1667,1,'Left Open',None),(.3334,0,.1666,1,'Left Open',None),(.5,0,.1667,1,'Right Open',None),(.6667,0,.1667,1,'Right Open',None),(.8334,0,.1666,1,'Right Open',None)]},
    'patioSlide2':   {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Sliding',None),(.5,0,.5,1,'Fixed',None)]},
    'patioSlide3':   {'unit':'door','shape':'rectangle','door':{'dtype':'double','leafCount':3,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.333,1,'Fixed',None),(.333,0,.334,1,'Sliding',None),(.667,0,.333,1,'Fixed',None)]},
    # shaped doors
    'doorArchedSingle':     {'unit':'door','shape':'arched','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',None)]},
    'doorArchedHalfGlazed': {'unit':'door','shape':'arched','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,.45,'Fixed',None),(0,.45,1,.55,'Right Open',None)]},
    'doorArchedDouble':     {'unit':'door','shape':'arched','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'doorArchedFrench':     {'unit':'door','shape':'arched','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'doorArchedWithSides':  {'unit':'door','shape':'arched','door':{'dtype':'full','leafCount':1,'slL':250,'slR':250,'flH':0},'panes':[(0,0,.22,1,'Fixed',None),(.22,0,.56,1,'Right Open',None),(.78,0,.22,1,'Fixed',None)]},
    'doorGothicSingle':     {'unit':'door','shape':'gothic','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',None)]},
    'doorGothicDouble':     {'unit':'door','shape':'gothic','door':{'dtype':'double','leafCount':2,'slL':0,'slR':0,'flH':0},'panes':[(0,0,.5,1,'Left Open',None),(.5,0,.5,1,'Right Open',None)]},
    'doorArchedGeorgian':   {'unit':'door','shape':'arched','door':{'dtype':'single','leafCount':1,'slL':0,'slR':0,'flH':0},'panes':[(0,0,1,1,'Right Open',{'v':1,'h':3})]},
}


def _bars_from_spec(spec):
    if not spec:
        return []
    bars = []
    nv, nh = spec.get('v', 0), spec.get('h', 0)
    for i in range(1, nv + 1):
        bars.append({'type': 'vertical',   'pos': i / (nv + 1), 'thickness': 18})
    for j in range(1, nh + 1):
        bars.append({'type': 'horizontal', 'pos': j / (nh + 1), 'thickness': 18})
    return bars


def _build_design_json(tpl_key, width, height, material, colour_hex, colour_name):
    """Assemble a design_json string matching the drawing-engine WindowModel shape."""
    import json
    tpl = _TPL.get(tpl_key, _TPL['single'])
    is_door = tpl.get('unit', 'window') == 'door'
    panes = []
    for i, (x, y, w, h, opening, bars) in enumerate(tpl['panes'], start=1):
        # infill: windows always glass; door leaves solid panel unless glazed
        if not is_door:
            infill = 'glass'
        elif bars or opening in ('Fixed', 'Sliding'):
            infill = 'glass'   # sidelights / fanlights / patio / barred = glazed
        else:
            infill = 'panel'   # solid door leaf
        panes.append({
            'id': f'p{i}', 'x': x, 'y': y, 'w': w, 'h': h,
            'opening': opening or 'Fixed',
            'glazing': 'Double, Low-E',
            'infill': infill,
            'glazingBars': _bars_from_spec(bars),
        })
    model = {
        'width': width, 'height': height,
        'shape': tpl.get('shape', 'rectangle'),
        'unitType': tpl.get('unit', 'window'),
        'archRise': 400,
        'barW': 68,
        'frame': {
            'material': material, 'thickness': 68,
            'color': colour_hex, 'colorName': colour_name,
            'slimMullionClip': False, 'staffBead': False,
        },
        'door': tpl.get('door', {'dtype': 'single', 'leafCount': 1, 'slL': 0, 'slR': 0, 'flH': 0}),
        'panes': panes,
        'hardware': {}, 'extras': {}, 'customExtras': [],
    }
    return json.dumps(model)


@projects_bp.route('/<int:project_id>/add', methods=['POST'])
@login_required
def add_unit(project_id):
    """Create a window/door from the chosen template, seed design_json, open editor."""
    try:
        project   = _own_project(project_id)
        unit_type = request.form.get('unit_type', 'window')
        tpl_key   = request.form.get('template_key', 'single')
        tpl_name  = request.form.get('template_name', '').strip()

        seq = project.windows.count()
        default_label = ('Door' if unit_type == 'door' else 'Window') + f' {seq + 1}'
        label = tpl_name and f'{default_label} · {tpl_name}' or default_label

        # sensible default sizes: doors are taller/narrower than windows
        if unit_type == 'door':
            width, height = 900, 2100
        else:
            width, height = 1200, 1400

        material   = 'Aluminium'
        colour_hex = '#2B2F33'
        colour_nm  = 'Anthracite'

        window = Window(
            project_id=project.id,
            tenant_id=current_user.tenant_id,
            label=label,
            width_mm=width,
            height_mm=height,
            material=material,
            frame_colour_hex=colour_hex,
            frame_colour_name=colour_nm,
            sequence_order=seq,
            design_json=_build_design_json(tpl_key, width, height,
                                           material, colour_hex, colour_nm),
        )
        db.session.add(window)
        db.session.flush()

        # keep a Pane row per template pane for downstream pricing/reports
        tpl = _TPL.get(tpl_key, _TPL['single'])
        for i, _ in enumerate(tpl['panes']):
            db.session.add(Pane(window_id=window.id, cell_key=f'c{i}'))
        db.session.commit()

        current_app.logger.info('Unit added: id=%d project=%d type=%s tpl=%s',
                                 window.id, project_id, unit_type, tpl_key)
        return redirect(url_for('editor.edit',
                                project_id=project.id, window_id=window.id))

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Error adding unit to project id=%d: %s', project_id, exc)
        flash('Could not add unit.', 'error')
        return redirect(url_for('projects.choose_unit', project_id=project_id))


# ------------------------------------------------------------------ #
#  Legacy quick-add (kept for backward compatibility) — routes to chooser
# ------------------------------------------------------------------ #
@projects_bp.route('/<int:project_id>/windows/new', methods=['POST'])
@login_required
def add_window(project_id):
    # Old inline "+ Add window" now sends the user through the chooser.
    return redirect(url_for('projects.choose_unit', project_id=project_id))


# ------------------------------------------------------------------ #
#  Internal helper — tenant isolation
# ------------------------------------------------------------------ #
def _own_project(project_id: int) -> Project:
    p = Project.query.filter_by(
        id=project_id, tenant_id=current_user.tenant_id
    ).first()
    if p is None:
        current_app.logger.warning('Project not found or access denied: id=%d tenant=%d',
                                    project_id, current_user.tenant_id)
        abort(404)
    return p