from ...extensions import db
from ...repositories import requirement_template_repo, lead_repo
from ...models.template_question import InputType


def list_project_types(tenant_id: int):
    return requirement_template_repo.list_project_types(tenant_id)


def get_project_type(tenant_id: int, project_type_id: int):
    return requirement_template_repo.get_project_type(tenant_id, project_type_id)


def get_questions(project_type_id: int):
    return requirement_template_repo.list_questions(project_type_id)


def start_or_resume(tenant_id: int, lead_id: int, project_type_id: int):
    """Customer opens the link -> picks a project type -> we create (or resume)
    a TemplateResponse so answers auto-save as they go."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')

    project_type = requirement_template_repo.get_project_type(tenant_id, project_type_id)
    if not project_type:
        raise LookupError('Project type not found')

    response = requirement_template_repo.get_response_by_lead(tenant_id, lead_id)
    if response and not response.is_submitted and response.project_type_id == project_type_id:
        return response

    if not response or response.is_submitted:
        response = requirement_template_repo.create_response(
            tenant_id=tenant_id, lead_id=lead_id, project_type_id=project_type_id, answers={}
        )
    else:
        # customer changed project type mid-way -> reset answers, keep same record
        requirement_template_repo.update_response(response, project_type_id=project_type_id, answers={})

    lead_repo.update(lead, project_type_id=project_type_id)
    db.session.commit()
    return response


def save_answer(tenant_id: int, response_id: int, question_key: str, value):
    """Auto-save a single answer -> called after every tap so a refresh never loses progress."""
    response = requirement_template_repo.get_response_by_id(tenant_id, response_id)
    if not response:
        raise LookupError('Template response not found')
    if response.is_submitted:
        raise ValueError('This requirement form has already been submitted')

    response.set_answer(question_key, value)
    db.session.commit()
    return response


def get_summary(response) -> dict:
    """Builds the plain-English confirmation summary shown before submit."""
    questions = requirement_template_repo.list_questions(response.project_type_id)
    items = []
    for q in questions:
        val = response.get_answer(q.question_key)
        if val in (None, '', []):
            continue
        items.append({'label': q.label, 'value': val})
    return {
        'project_type': response.project_type,
        'answer_list': items,
    }


def submit(tenant_id: int, response_id: int):
    from datetime import datetime
    response = requirement_template_repo.get_response_by_id(tenant_id, response_id)
    if not response:
        raise LookupError('Template response not found')
    if response.is_submitted:
        return response

    requirement_template_repo.update_response(
        response, is_submitted=True, submitted_at=datetime.utcnow()
    )
    db.session.commit()

    from . import template_mapping_service
    template_mapping_service.map_to_preliminary_selection(tenant_id, response)

    return response
