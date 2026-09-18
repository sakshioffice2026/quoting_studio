from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..services.domain import preliminary_selection_service, lead_service

presel_bp = Blueprint('presel', __name__)


@presel_bp.route('/leads/<int:lead_id>/preliminary-selection/start', methods=['POST'])
@login_required
def start(lead_id):
    try:
        presel = preliminary_selection_service.start_preliminary_selection(
            tenant_id=current_user.tenant_id,
            lead_id=lead_id,
            created_by=current_user.id,
            survey_required=bool(request.form.get('survey_required')),
        )
        flash('Preliminary selection started.', 'success')
        return redirect(url_for('presel.detail', presel_id=presel.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('leads.detail', lead_id=lead_id))


@presel_bp.route('/preliminary-selections/<int:presel_id>')
@login_required
def detail(presel_id):
    presel = preliminary_selection_service.get_preselection(current_user.tenant_id, presel_id)
    if not presel:
        flash('Preliminary selection not found.', 'error')
        return redirect(url_for('leads.index'))
    lead = lead_service.get_lead(current_user.tenant_id, presel.lead_id)
    return render_template('presel_detail.html', presel=presel, lead=lead)


@presel_bp.route('/preliminary-selections/<int:presel_id>/update', methods=['POST'])
@login_required
def update(presel_id):
    try:
        preliminary_selection_service.update_preselection(
            current_user.tenant_id, presel_id,
            shortlisted_ranges=request.form.get('shortlisted_ranges') or None,
            rough_opening_doors=request.form.get('rough_opening_doors', type=int),
            rough_opening_windows=request.form.get('rough_opening_windows', type=int),
            indicative_price_min=request.form.get('indicative_price_min', type=float),
            indicative_price_max=request.form.get('indicative_price_max', type=float),
            survey_required=bool(request.form.get('survey_required')),
            notes=request.form.get('notes') or None,
        )
        flash('Preliminary selection updated.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('presel.detail', presel_id=presel_id))


@presel_bp.route('/preliminary-selections/<int:presel_id>/shortlist', methods=['POST'])
@login_required
def shortlist(presel_id):
    try:
        preliminary_selection_service.shortlist(current_user.tenant_id, presel_id)
        flash('Marked as shortlisted.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('presel.detail', presel_id=presel_id))


@presel_bp.route('/preliminary-selections/<int:presel_id>/hold', methods=['POST'])
@login_required
def hold(presel_id):
    try:
        preliminary_selection_service.put_on_hold(current_user.tenant_id, presel_id, request.form.get('notes') or None)
        flash('Put on hold.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('presel.detail', presel_id=presel_id))


@presel_bp.route('/preliminary-selections/<int:presel_id>/drop', methods=['POST'])
@login_required
def drop(presel_id):
    try:
        preliminary_selection_service.drop(current_user.tenant_id, presel_id, request.form.get('notes') or None)
        flash('Preliminary selection dropped.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('presel.detail', presel_id=presel_id))


@presel_bp.route('/preliminary-selections/<int:presel_id>/confirm-survey', methods=['POST'])
@login_required
def confirm_survey(presel_id):
    try:
        preliminary_selection_service.confirm_survey(current_user.tenant_id, presel_id)
        flash('Survey confirmed. Ready to move to Survey stage.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('presel.detail', presel_id=presel_id))
