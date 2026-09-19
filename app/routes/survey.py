from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..services.domain import survey_service, preliminary_selection_service, lead_service

survey_bp = Blueprint('survey', __name__)


def _parse_date(value):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_flags(raw):
    if not raw:
        return None
    return [f.strip() for f in raw.split(',') if f.strip()]


@survey_bp.route('/preliminary-selections/<int:presel_id>/survey/schedule', methods=['POST'])
@login_required
def schedule(presel_id):
    try:
        survey = survey_service.schedule_survey(
            tenant_id=current_user.tenant_id,
            presel_id=presel_id,
            created_by=current_user.id,
            scheduled_date=_parse_date(request.form.get('scheduled_date')),
            surveyor_name=request.form.get('surveyor_name') or None,
            notes=request.form.get('notes') or None,
        )
        flash('Survey scheduled.', 'success')
        return redirect(url_for('survey.detail', survey_id=survey.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('presel.detail', presel_id=presel_id))


@survey_bp.route('/surveys/<int:survey_id>')
@login_required
def detail(survey_id):
    from ..services.domain import design_approval_service
    survey = survey_service.get_survey(current_user.tenant_id, survey_id)
    if not survey:
        flash('Survey not found.', 'error')
        return redirect(url_for('leads.index'))
    lead = lead_service.get_lead(current_user.tenant_id, survey.lead_id)
    openings = survey.openings.all()
    latest_design_approval = design_approval_service.get_latest_for_project(
        current_user.tenant_id, survey.project_id)
    return render_template('survey_detail.html', survey=survey, lead=lead, openings=openings,
                           latest_design_approval=latest_design_approval)


@survey_bp.route('/surveys/<int:survey_id>/reschedule', methods=['POST'])
@login_required
def reschedule(survey_id):
    try:
        survey_service.reschedule(
            current_user.tenant_id, survey_id,
            scheduled_date=_parse_date(request.form.get('scheduled_date')),
            notes=request.form.get('notes') or None,
        )
        flash('Survey rescheduled.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('survey.detail', survey_id=survey_id))


@survey_bp.route('/surveys/<int:survey_id>/openings', methods=['POST'])
@login_required
def add_opening(survey_id):
    try:
        survey_service.add_opening(
            tenant_id=current_user.tenant_id,
            survey_id=survey_id,
            opening_label=request.form.get('opening_label'),
            location_room=request.form.get('location_room') or None,
            measured_width_mm=request.form.get('measured_width_mm', type=int),
            measured_height_mm=request.form.get('measured_height_mm', type=int),
            wall_thickness_mm=request.form.get('wall_thickness_mm', type=int),
            sill_height_mm=request.form.get('sill_height_mm', type=int),
            site_condition_notes=request.form.get('site_condition_notes') or None,
            site_issue_flags=_parse_flags(request.form.get('site_issue_flags')),
        )
        flash('Opening added.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('survey.detail', survey_id=survey_id))


@survey_bp.route('/surveys/<int:survey_id>/openings/<int:opening_id>/delete', methods=['POST'])
@login_required
def delete_opening(survey_id, opening_id):
    try:
        survey_service.delete_opening(current_user.tenant_id, opening_id)
        flash('Opening removed.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('survey.detail', survey_id=survey_id))


@survey_bp.route('/surveys/<int:survey_id>/accept-issues', methods=['POST'])
@login_required
def accept_issues(survey_id):
    try:
        survey_service.accept_issues(current_user.tenant_id, survey_id)
        flash('Site issues accepted by customer.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('survey.detail', survey_id=survey_id))


@survey_bp.route('/surveys/<int:survey_id>/complete', methods=['POST'])
@login_required
def complete(survey_id):
    try:
        survey = survey_service.complete_survey(current_user.tenant_id, survey_id)
        flash('Survey completed. Add windows/doors, then submit for design approval.', 'success')
        if survey.project_id:
            return redirect(url_for('projects.detail', project_id=survey.project_id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('survey.detail', survey_id=survey_id))
