import json
from datetime import datetime

from ...extensions import db
from ...repositories import survey_repo, preliminary_selection_repo
from ...models.survey import SurveyStatus
from ...models.preliminary_selection import PreselStatus


def get_survey(tenant_id: int, survey_id: int):
    return survey_repo.get_by_id(tenant_id, survey_id)


def get_by_lead(tenant_id: int, lead_id: int):
    return survey_repo.get_by_lead(tenant_id, lead_id)


def get_by_presel(tenant_id: int, presel_id: int):
    return survey_repo.get_by_presel(tenant_id, presel_id)


def list_surveys(tenant_id: int, status: str | None = None):
    return survey_repo.list_all(tenant_id, status=status)


def schedule_survey(tenant_id: int, presel_id: int, created_by: int,
                     scheduled_date=None, surveyor_name=None, notes=None):
    """Approval gate from Phase 2: customer agrees to a paid/scheduled site
    survey -> creates the Survey record (Phase 3). Requires PRESEL-SHORTLISTED
    and survey_required=True."""
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    if presel.status != PreselStatus.SHORTLISTED:
        raise ValueError('Preliminary selection must be PRESEL-SHORTLISTED before survey can be scheduled')
    if not presel.survey_required:
        raise ValueError('This preliminary selection does not require a survey')

    existing = survey_repo.get_by_presel(tenant_id, presel_id)
    if existing:
        return existing

    survey = survey_repo.create(
        tenant_id=tenant_id,
        lead_id=presel.lead_id,
        project_id=presel.project_id,
        presel_id=presel.id,
        created_by=created_by,
        scheduled_date=scheduled_date,
        surveyor_name=surveyor_name,
        notes=notes,
        status=SurveyStatus.SCHEDULED,
    )
    db.session.commit()
    return survey


def reschedule(tenant_id: int, survey_id: int, scheduled_date=None, notes=None):
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    fields = {'status': SurveyStatus.RESCHEDULED}
    if scheduled_date:
        fields['scheduled_date'] = scheduled_date
    if notes:
        fields['notes'] = notes
    survey_repo.update(survey, **fields)
    db.session.commit()
    return survey


def add_opening(tenant_id: int, survey_id: int, opening_label: str, location_room=None,
                 measured_width_mm=None, measured_height_mm=None, wall_thickness_mm=None,
                 sill_height_mm=None, site_condition_notes=None, photo_refs=None,
                 site_issue_flags=None):
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    if not opening_label:
        raise ValueError('Opening label is required')

    opening = survey_repo.create_opening(
        tenant_id=tenant_id,
        survey_id=survey.id,
        opening_label=opening_label,
        location_room=location_room,
        measured_width_mm=measured_width_mm,
        measured_height_mm=measured_height_mm,
        wall_thickness_mm=wall_thickness_mm,
        sill_height_mm=sill_height_mm,
        site_condition_notes=site_condition_notes,
        photo_refs=json.dumps(photo_refs) if photo_refs else None,
        site_issue_flags=json.dumps(site_issue_flags) if site_issue_flags else None,
    )

    if site_issue_flags:
        survey_repo.update(survey, status=SurveyStatus.ISSUES_FOUND)

    db.session.commit()
    return opening


def update_opening(tenant_id: int, opening_id: int, **fields):
    opening = survey_repo.get_opening_by_id(tenant_id, opening_id)
    if not opening:
        raise LookupError('Survey opening not found')

    if 'photo_refs' in fields and fields['photo_refs'] is not None and not isinstance(fields['photo_refs'], str):
        fields['photo_refs'] = json.dumps(fields['photo_refs'])
    if 'site_issue_flags' in fields and fields['site_issue_flags'] is not None and not isinstance(fields['site_issue_flags'], str):
        fields['site_issue_flags'] = json.dumps(fields['site_issue_flags'])

    survey_repo.update_opening(opening, **fields)

    if fields.get('site_issue_flags'):
        survey = survey_repo.get_by_id(tenant_id, opening.survey_id)
        if survey and survey.status == SurveyStatus.COMPLETED:
            survey_repo.update(survey, status=SurveyStatus.ISSUES_FOUND)

    db.session.commit()
    return opening


def delete_opening(tenant_id: int, opening_id: int):
    opening = survey_repo.get_opening_by_id(tenant_id, opening_id)
    if not opening:
        raise LookupError('Survey opening not found')
    survey_repo.delete_opening(opening)
    db.session.commit()


def complete_survey(tenant_id: int, survey_id: int):
    """Approval gate: all openings measured and report reviewed internally
    (no blocking site issues, or issues resolved/accepted) -> moves to
    Design & Specs. Blocked while any opening still carries open site_issue_flags."""
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    if survey.opening_count == 0:
        raise ValueError('At least one opening must be measured before completing the survey')
    if survey.has_blocking_issues:
        raise ValueError('Resolve or accept flagged site issues before completing the survey')

    survey_repo.update(
        survey,
        status=SurveyStatus.COMPLETED,
        completed_date=datetime.utcnow().date(),
    )
    db.session.commit()
    return survey


def mark_issues_found(tenant_id: int, survey_id: int, notes=None):
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    fields = {'status': SurveyStatus.ISSUES_FOUND}
    if notes:
        fields['notes'] = notes
    survey_repo.update(survey, **fields)
    db.session.commit()
    return survey


def accept_issues(tenant_id: int, survey_id: int):
    """Customer accepts flagged issues as-is -> clears the block so the
    survey can be completed and move on to Design & Specs."""
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    for opening in survey_repo.list_openings(tenant_id, survey_id):
        if opening.site_issue_flags:
            survey_repo.update_opening(opening, site_issue_flags=None)
    db.session.commit()
    return survey


def delete_survey(tenant_id: int, survey_id: int):
    survey = survey_repo.get_by_id(tenant_id, survey_id)
    if not survey:
        raise LookupError('Survey not found')
    survey_repo.delete(survey)
    db.session.commit()
