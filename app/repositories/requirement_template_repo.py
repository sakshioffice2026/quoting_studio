from ..extensions import db
from ..models import ProjectType, TemplateQuestion, TemplateResponse, TemplateUpload


# ---- ProjectType ----

def list_project_types(tenant_id: int, active_only: bool = True):
    q = ProjectType.query.filter_by(tenant_id=tenant_id)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(ProjectType.name).all()


def get_project_type(tenant_id: int, project_type_id: int):
    return ProjectType.query.filter_by(tenant_id=tenant_id, id=project_type_id).first()


def list_project_types_by_ids(tenant_id: int, project_type_ids: list):
    if not project_type_ids:
        return []
    return (ProjectType.query
            .filter(ProjectType.tenant_id == tenant_id, ProjectType.id.in_(project_type_ids))
            .order_by(ProjectType.name)
            .all())


# ---- TemplateQuestion ----

def list_questions(project_type_id: int):
    return (TemplateQuestion.query
            .filter_by(project_type_id=project_type_id)
            .order_by(TemplateQuestion.step_order)
            .all())


def list_questions_for_types(project_type_ids: list):
    """Merged, ordered question set across multiple selected categories
    (e.g. Windows + Doors picked together)."""
    if not project_type_ids:
        return []
    return (TemplateQuestion.query
            .filter(TemplateQuestion.project_type_id.in_(project_type_ids))
            .order_by(TemplateQuestion.project_type_id, TemplateQuestion.step_order)
            .all())


# ---- TemplateResponse ----

def get_response_by_id(tenant_id: int, response_id: int):
    return TemplateResponse.query.filter_by(tenant_id=tenant_id, id=response_id).first()


def get_response_by_lead(tenant_id: int, lead_id: int):
    return (TemplateResponse.query
            .filter_by(tenant_id=tenant_id, lead_id=lead_id)
            .order_by(TemplateResponse.created_at.desc())
            .first())


def create_response(tenant_id: int, lead_id: int, project_type_id: int, **fields) -> TemplateResponse:
    response = TemplateResponse(
        tenant_id=tenant_id, lead_id=lead_id, project_type_id=project_type_id, **fields
    )
    db.session.add(response)
    db.session.flush()
    return response


def update_response(response: TemplateResponse, **fields) -> TemplateResponse:
    for key, value in fields.items():
        if hasattr(response, key):
            setattr(response, key, value)
    db.session.flush()
    return response


# ---- TemplateUpload ----

def create_upload(tenant_id: int, response_id: int, **fields) -> TemplateUpload:
    upload = TemplateUpload(tenant_id=tenant_id, response_id=response_id, **fields)
    db.session.add(upload)
    db.session.flush()
    return upload


def list_uploads(response_id: int):
    return (TemplateUpload.query
            .filter_by(response_id=response_id)
            .order_by(TemplateUpload.uploaded_at)
            .all())
