from ..extensions import db
from ..models import ProjectType, TemplateQuestion, TemplateResponse


# ---- ProjectType ----

def list_project_types(tenant_id: int, active_only: bool = True):
    q = ProjectType.query.filter_by(tenant_id=tenant_id)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(ProjectType.name).all()


def get_project_type(tenant_id: int, project_type_id: int):
    return ProjectType.query.filter_by(tenant_id=tenant_id, id=project_type_id).first()


# ---- TemplateQuestion ----

def list_questions(project_type_id: int):
    return (TemplateQuestion.query
            .filter_by(project_type_id=project_type_id)
            .order_by(TemplateQuestion.step_order)
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
