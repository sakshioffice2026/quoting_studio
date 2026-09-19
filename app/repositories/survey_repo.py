from ..extensions import db
from ..models import Survey, SurveyOpening


def get_by_id(tenant_id: int, survey_id: int):
    return Survey.query.filter_by(tenant_id=tenant_id, id=survey_id).first()


def get_by_lead(tenant_id: int, lead_id: int):
    return (Survey.query
            .filter_by(tenant_id=tenant_id, lead_id=lead_id)
            .order_by(Survey.created_at.desc())
            .first())


def get_by_presel(tenant_id: int, presel_id: int):
    return (Survey.query
            .filter_by(tenant_id=tenant_id, presel_id=presel_id)
            .order_by(Survey.created_at.desc())
            .first())


def get_by_project(tenant_id: int, project_id: int):
    return (Survey.query
            .filter_by(tenant_id=tenant_id, project_id=project_id)
            .order_by(Survey.created_at.desc())
            .first())


def list_all(tenant_id: int, status: str | None = None):
    q = Survey.query.filter_by(tenant_id=tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(Survey.created_at.desc()).all()


def create(tenant_id: int, **fields) -> Survey:
    survey = Survey(tenant_id=tenant_id, **fields)
    db.session.add(survey)
    db.session.flush()
    return survey


def update(survey: Survey, **fields) -> Survey:
    for key, value in fields.items():
        if hasattr(survey, key):
            setattr(survey, key, value)
    db.session.flush()
    return survey


def delete(survey: Survey) -> None:
    db.session.delete(survey)
    db.session.flush()


def get_opening_by_id(tenant_id: int, opening_id: int):
    return SurveyOpening.query.filter_by(tenant_id=tenant_id, id=opening_id).first()


def list_openings(tenant_id: int, survey_id: int):
    return (SurveyOpening.query
            .filter_by(tenant_id=tenant_id, survey_id=survey_id)
            .order_by(SurveyOpening.id.asc())
            .all())


def create_opening(tenant_id: int, **fields) -> SurveyOpening:
    opening = SurveyOpening(tenant_id=tenant_id, **fields)
    db.session.add(opening)
    db.session.flush()
    return opening


def update_opening(opening: SurveyOpening, **fields) -> SurveyOpening:
    for key, value in fields.items():
        if hasattr(opening, key):
            setattr(opening, key, value)
    db.session.flush()
    return opening


def delete_opening(opening: SurveyOpening) -> None:
    db.session.delete(opening)
    db.session.flush()
