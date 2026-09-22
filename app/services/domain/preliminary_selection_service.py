from ...extensions import db
from ...repositories import preliminary_selection_repo, lead_repo
from ...models.preliminary_selection import PreselStatus
from ...models.lead import FollowUpStatus
from ...models.project import Project, ProjectStatus


def get_preselection(tenant_id: int, presel_id: int):
    return preliminary_selection_repo.get_by_id(tenant_id, presel_id)


def get_by_lead(tenant_id: int, lead_id: int):
    return preliminary_selection_repo.get_by_lead(tenant_id, lead_id)


def list_preselections(tenant_id: int, status: str | None = None):
    return preliminary_selection_repo.list_all(tenant_id, status=status)


def _get_or_create_project_for_lead(tenant_id: int, lead, created_by: int) -> Project:
    """Lead -> Project creation point. A qualified lead gets exactly one Project;
    re-entry into Preliminary Selection reuses the same Project."""
    if lead.project_id:
        project = Project.query.filter_by(tenant_id=tenant_id, id=lead.project_id).first()
        if project:
            return project

    project = Project(
        tenant_id=tenant_id,
        created_by=created_by,
        customer_name=lead.customer_name,
        customer_id=lead.customer_id,
        project_name=lead.project_name or None,
        address=lead.project_address,
        status=ProjectStatus.DRAFT,
    )
    db.session.add(project)
    db.session.flush()

    lead_repo.update(lead, project_id=project.id)
    return project


def start_preliminary_selection(tenant_id: int, lead_id: int, created_by: int,
                                 shortlisted_ranges=None, rough_opening_doors=None,
                                 rough_opening_windows=None, indicative_price_min=None,
                                 indicative_price_max=None, survey_required=True, notes=None):
    """Triggers on: qualified lead with a scheduled meeting.
    Creates (or reuses) the Project tied to the Lead, then opens a Preliminary
    Selection record against it. If the customer already filled a Requirement
    Template, its mapped answers are used to pre-fill any field not explicitly passed."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')
    if lead.follow_up_status != FollowUpStatus.QUALIFIED:
        raise ValueError('Lead must be FUP-QUALIFIED before preliminary selection can start')

    project = _get_or_create_project_for_lead(tenant_id, lead, created_by)

    template_defaults = {}
    from ...repositories import requirement_template_repo
    template_response = requirement_template_repo.get_response_by_lead(tenant_id, lead_id)
    if template_response and template_response.is_submitted:
        from . import template_mapping_service
        template_defaults = template_mapping_service.build_mapped_fields(template_response)

    presel = preliminary_selection_repo.create(
        tenant_id=tenant_id,
        lead_id=lead.id,
        project_id=project.id,
        created_by=created_by,
        shortlisted_ranges=shortlisted_ranges or template_defaults.get('shortlisted_ranges'),
        rough_opening_doors=rough_opening_doors if rough_opening_doors is not None else template_defaults.get('rough_opening_doors'),
        rough_opening_windows=rough_opening_windows if rough_opening_windows is not None else template_defaults.get('rough_opening_windows'),
        indicative_price_min=indicative_price_min if indicative_price_min is not None else template_defaults.get('indicative_price_min'),
        indicative_price_max=indicative_price_max if indicative_price_max is not None else template_defaults.get('indicative_price_max'),
        survey_required=survey_required,
        notes=notes,
        status=PreselStatus.IN_PROGRESS,
    )
    db.session.commit()
    return presel


def update_preselection(tenant_id: int, presel_id: int, **fields):
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    preliminary_selection_repo.update(presel, **fields)
    db.session.commit()
    return presel


def shortlist(tenant_id: int, presel_id: int):
    """Customer picked a direction -> PRESEL-SHORTLISTED."""
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    preliminary_selection_repo.update(presel, status=PreselStatus.SHORTLISTED)
    db.session.commit()
    return presel


def put_on_hold(tenant_id: int, presel_id: int, notes: str | None = None):
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    fields = {'status': PreselStatus.ON_HOLD}
    if notes:
        fields['notes'] = notes
    preliminary_selection_repo.update(presel, **fields)
    db.session.commit()
    return presel


def drop(tenant_id: int, presel_id: int, notes: str | None = None):
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    fields = {'status': PreselStatus.DROPPED}
    if notes:
        fields['notes'] = notes
    preliminary_selection_repo.update(presel, **fields)
    db.session.commit()
    return presel


def confirm_survey(tenant_id: int, presel_id: int, created_by: int,
                    scheduled_date=None, surveyor_name=None, notes=None):
    """Approval gate: customer agrees to a paid/scheduled site survey -> creates
    the Survey record and moves to Survey (Phase 3).
    Requires PRESEL-SHORTLISTED and survey_required=True."""
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    if presel.status != PreselStatus.SHORTLISTED:
        raise ValueError('Preliminary selection must be PRESEL-SHORTLISTED before survey can be scheduled')
    if not presel.survey_required:
        raise ValueError('This preliminary selection does not require a survey')

    from . import survey_service
    return survey_service.schedule_survey(
        tenant_id=tenant_id,
        presel_id=presel_id,
        created_by=created_by,
        scheduled_date=scheduled_date,
        surveyor_name=surveyor_name,
        notes=notes,
    )


def delete_preselection(tenant_id: int, presel_id: int):
    presel = preliminary_selection_repo.get_by_id(tenant_id, presel_id)
    if not presel:
        raise LookupError('Preliminary selection not found')
    preliminary_selection_repo.delete(presel)
    db.session.commit()
