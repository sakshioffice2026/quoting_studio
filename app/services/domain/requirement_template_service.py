import os
from ...extensions import db
from ...repositories import requirement_template_repo, lead_repo
from ...models.template_question import InputType

SITE_TYPES = [
    {'key': 'residential', 'label': 'Residential', 'icon': '🏠'},
    {'key': 'commercial',  'label': 'Commercial',  'icon': '🏢'},
    {'key': 'industrial',  'label': 'Industrial',  'icon': '🏭'},
]


def list_project_types(tenant_id: int):
    return requirement_template_repo.list_project_types(tenant_id)


def get_project_type(tenant_id: int, project_type_id: int):
    return requirement_template_repo.get_project_type(tenant_id, project_type_id)


def get_questions(project_type_id: int):
    return requirement_template_repo.list_questions(project_type_id)


def get_questions_for_response(response):
    """Return merged ordered question list across all selected project types."""
    ids = response.project_type_ids or (
        [response.project_type_id] if response.project_type_id else []
    )
    return requirement_template_repo.list_questions_for_types(ids)


def get_in_progress_response(tenant_id: int, lead_id: int):
    """Return an unsubmitted response for this lead, or None."""
    response = requirement_template_repo.get_response_by_lead(tenant_id, lead_id)
    if response and not response.is_submitted:
        return response
    return None


def start_or_resume(tenant_id: int, lead_id: int, project_type_ids: list, site_type: str = None):
    """Customer picks one or more project types + site type -> create or resume a TemplateResponse."""
    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')

    if not project_type_ids:
        raise ValueError('At least one project type must be selected')

    project_types = requirement_template_repo.list_project_types_by_ids(tenant_id, project_type_ids)
    if not project_types:
        raise LookupError('Project type not found')

    response = requirement_template_repo.get_response_by_lead(tenant_id, lead_id)

    if response and not response.is_submitted:
        requirement_template_repo.update_response(
            response,
            project_type_ids=project_type_ids,
            project_type_id=project_type_ids[0] if project_type_ids else None,
            site_type=site_type,
            answers={},
        )
    else:
        response = requirement_template_repo.create_response(
            tenant_id=tenant_id,
            lead_id=lead_id,
            project_type_id=project_type_ids[0] if project_type_ids else None,
            project_type_ids=project_type_ids,
            site_type=site_type,
            answers={},
        )

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


def save_upload(tenant_id: int, response_id: int, file_storage):
    """Save a site photo / floor plan upload attached to this response."""
    from ...models import TemplateUpload
    import uuid

    response = requirement_template_repo.get_response_by_id(tenant_id, response_id)
    if not response:
        raise LookupError('Template response not found')

    original_filename = file_storage.filename
    ext = os.path.splitext(original_filename)[1].lower()
    stored_filename = f"{uuid.uuid4().hex}{ext}"

    from flask import current_app
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'template_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, stored_filename))

    upload = requirement_template_repo.create_upload(
        tenant_id=tenant_id,
        response_id=response_id,
        stored_filename=stored_filename,
        original_filename=original_filename,
        content_type=file_storage.content_type,
        file_size=None,
    )
    db.session.commit()
    return upload


def get_summary(response) -> dict:
    """Builds the plain-English confirmation summary shown before submit and on lead detail."""
    ids = response.project_type_ids or (
        [response.project_type_id] if response.project_type_id else []
    )
    questions = requirement_template_repo.list_questions_for_types(ids)
    items = []
    for q in questions:
        val = response.get_answer(q.question_key)
        if val in (None, '', []):
            continue
        items.append({'label': q.label, 'value': val})

    project_types = response.project_types  # list of ProjectType ORM objects

    combined_name = ' + '.join(pt.name for pt in project_types) if project_types else ''
    combined_icon = (project_types[0].icon or '') if project_types else ''

    class _ProjectTypeFacade:
        def __init__(self, name, icon):
            self.name = name
            self.icon = icon

    # Extract material, color, finish from mapped fields
    material_keys = {'material', 'material_type', 'frame_material'}
    color_keys    = {'color', 'colour', 'finish', 'frame_color', 'frame_colour', 'frame_finish'}

    material_val = None
    color_val    = None

    for q in questions:
        key_lower = (q.question_key or '').lower()
        maps_lower = (q.maps_to_field or '').lower()
        val = response.get_answer(q.question_key)
        if val in (None, '', []):
            continue
        if key_lower in material_keys or maps_lower in material_keys:
            material_val = val if not isinstance(val, list) else ', '.join(val)
        if key_lower in color_keys or maps_lower in color_keys:
            color_val = val if not isinstance(val, list) else ', '.join(val)

    return {
        'project_type':  _ProjectTypeFacade(combined_name, combined_icon),
        'project_types': project_types,
        'site_type':     response.site_type,
        'answer_list':   items,
        'material':      material_val,
        'color':         color_val,
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
