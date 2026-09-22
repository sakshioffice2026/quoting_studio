from flask import Blueprint, render_template, request, jsonify, abort

from ..services.domain import requirement_template_service
from ..models import Lead, TemplateResponse

template_bp = Blueprint('template', __name__, url_prefix='/rt')


@template_bp.route('/<int:lead_id>')
def landing(lead_id):
    """Public entry point sent to the customer (SMS/email link).
    Asks site type first, then lets them pick one or more categories
    (Windows and/or Doors) to configure together."""
    lead = Lead.query.get_or_404(lead_id)

    project_types = requirement_template_service.list_project_types(lead.tenant_id)
    site_types = requirement_template_service.SITE_TYPES
    in_progress = requirement_template_service.get_in_progress_response(lead.tenant_id, lead_id)
    return render_template(
        'requirement_template/landing.html',
        lead=lead, project_types=project_types, site_types=site_types, in_progress=in_progress
    )


@template_bp.route('/<int:lead_id>/start', methods=['POST'])
def start(lead_id):
    """Accepts one or more project_type_ids plus the chosen site_type,
    so the customer can configure Windows and Doors in the same wizard."""
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    project_type_ids = data.get('project_type_ids') or []
    site_type = data.get('site_type')

    try:
        project_type_ids = [int(i) for i in project_type_ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid project_type_ids'}), 400

    try:
        response = requirement_template_service.start_or_resume(
            lead.tenant_id, lead_id, project_type_ids, site_type
        )
    except LookupError:
        abort(404)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'response_id': response.id})


@template_bp.route('/response/<int:response_id>')
def wizard(response_id):
    """The one-question-per-screen wizard shell. Actual question navigation
    happens client-side; this just bootstraps state."""
    response = TemplateResponse.query.get_or_404(response_id)
    questions = requirement_template_service.get_questions_for_response(response)
    return render_template(
        'requirement_template/wizard.html',
        response=response, questions=questions, project_types=response.project_types
    )


@template_bp.route('/response/<int:response_id>/answer', methods=['POST'])
def save_answer(response_id):
    """Auto-save endpoint, called after every tap. Keeps progress even on refresh."""
    response = TemplateResponse.query.get_or_404(response_id)
    data = request.get_json(silent=True) or {}
    question_key = data.get('question_key')
    value = data.get('value')

    if not question_key:
        return jsonify({'error': 'question_key required'}), 400

    try:
        requirement_template_service.save_answer(response.tenant_id, response_id, question_key, value)
    except (LookupError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'ok': True})


@template_bp.route('/response/<int:response_id>/upload', methods=['POST'])
def upload(response_id):
    """Optional site photo / floor plan upload, attached to this response."""
    response = TemplateResponse.query.get_or_404(response_id)
    file_storage = request.files.get('file')

    if not file_storage or not file_storage.filename:
        return jsonify({'error': 'No file provided'}), 400

    try:
        saved = requirement_template_service.save_upload(response.tenant_id, response_id, file_storage)
    except (LookupError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'ok': True, 'upload': saved.to_dict()})


@template_bp.route('/response/<int:response_id>/summary')
def summary(response_id):
    """Plain-English confirmation screen before final submit."""
    response = TemplateResponse.query.get_or_404(response_id)
    summary_data = requirement_template_service.get_summary(response)
    return render_template(
        'requirement_template/summary.html',
        response=response, summary=summary_data
    )


@template_bp.route('/response/<int:response_id>/submit', methods=['POST'])
def submit(response_id):
    response = TemplateResponse.query.get_or_404(response_id)
    requirement_template_service.submit(response.tenant_id, response_id)
    return render_template('requirement_template/thank_you.html', response=response)
