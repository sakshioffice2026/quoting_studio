from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from ..services import customer_service, lead_service, interaction_service

leads_api_bp = Blueprint('leads_api', __name__)


def _err(exc, code=400):
    return jsonify({'error': str(exc)}), code


# ------------------------------------------------------------------ #
#  Customers
# ------------------------------------------------------------------ #
@leads_api_bp.route('/customers', methods=['GET'])
@login_required
def list_customers():
    search = request.args.get('q') or None
    customers = customer_service.list_customers(current_user.tenant_id, search=search)
    return jsonify([c.to_dict() for c in customers])


@leads_api_bp.route('/customers/<int:customer_id>', methods=['GET'])
@login_required
def get_customer(customer_id):
    customer = customer_service.get_customer(current_user.tenant_id, customer_id)
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    return jsonify(customer.to_dict())


@leads_api_bp.route('/customers', methods=['POST'])
@login_required
def create_customer():
    data = request.get_json(force=True) or {}
    try:
        customer = customer_service.create_customer(
            tenant_id=current_user.tenant_id,
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email'),
            city=data.get('city'),
            address=data.get('address'),
            notes=data.get('notes'),
        )
        return jsonify(customer.to_dict()), 201
    except ValueError as exc:
        return _err(exc)
    except Exception as exc:
        current_app.logger.exception('create_customer error: %s', exc)
        return _err('Failed to create customer', 500)


@leads_api_bp.route('/customers/<int:customer_id>', methods=['PATCH'])
@login_required
def update_customer(customer_id):
    data = request.get_json(force=True) or {}
    try:
        customer = customer_service.update_customer(current_user.tenant_id, customer_id, **data)
        return jsonify(customer.to_dict())
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('update_customer error: %s', exc)
        return _err('Failed to update customer', 500)


# ------------------------------------------------------------------ #
#  Leads
# ------------------------------------------------------------------ #
@leads_api_bp.route('/leads', methods=['GET'])
@login_required
def list_leads():
    status = request.args.get('status') or None
    assigned_to = request.args.get('assigned_to', type=int)
    leads = lead_service.list_leads(current_user.tenant_id, status=status, assigned_to=assigned_to)
    return jsonify([l.to_dict() for l in leads])


@leads_api_bp.route('/leads/<int:lead_id>', methods=['GET'])
@login_required
def get_lead(lead_id):
    lead = lead_service.get_lead(current_user.tenant_id, lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404
    return jsonify(lead.to_dict())


@leads_api_bp.route('/leads', methods=['POST'])
@login_required
def create_lead():
    data = request.get_json(force=True) or {}
    try:
        lead = lead_service.create_lead(
            tenant_id=current_user.tenant_id,
            customer_name=data.get('customer_name'),
            phone=data.get('phone'),
            email=data.get('email'),
            source_channel=data.get('source_channel', 'website'),
            project_city=data.get('project_city'),
            project_address=data.get('project_address'),
            product_interest=data.get('product_interest'),
            approx_quantity=data.get('approx_quantity'),
            budget_band=data.get('budget_band'),
        )
        return jsonify(lead.to_dict()), 201
    except ValueError as exc:
        return _err(exc)
    except Exception as exc:
        current_app.logger.exception('create_lead error: %s', exc)
        return _err('Failed to create lead', 500)


@leads_api_bp.route('/leads/<int:lead_id>', methods=['PATCH'])
@login_required
def update_lead(lead_id):
    data = request.get_json(force=True) or {}
    try:
        lead = lead_service.update_lead(current_user.tenant_id, lead_id, **data)
        return jsonify(lead.to_dict())
    except LookupError as exc:
        return _err(exc, 404)
    except Exception as exc:
        current_app.logger.exception('update_lead error: %s', exc)
        return _err('Failed to update lead', 500)


@leads_api_bp.route('/leads/<int:lead_id>/assign', methods=['POST'])
@login_required
def assign_lead(lead_id):
    data = request.get_json(force=True) or {}
    try:
        lead = lead_service.assign_lead(current_user.tenant_id, lead_id, int(data.get('assigned_to')))
        return jsonify(lead.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


@leads_api_bp.route('/leads/<int:lead_id>/invalidate', methods=['POST'])
@login_required
def invalidate_lead(lead_id):
    data = request.get_json(force=True) or {}
    try:
        lead = lead_service.mark_invalid(current_user.tenant_id, lead_id, data.get('reason'))
        return jsonify(lead.to_dict())
    except LookupError as exc:
        return _err(exc, 404)


@leads_api_bp.route('/leads/<int:lead_id>/qualify', methods=['POST'])
@login_required
def qualify_lead(lead_id):
    try:
        lead = lead_service.qualify_lead(current_user.tenant_id, lead_id)
        return jsonify(lead.to_dict())
    except LookupError as exc:
        return _err(exc, 404)


@leads_api_bp.route('/leads/<int:lead_id>/follow-up-status', methods=['POST'])
@login_required
def set_follow_up_status(lead_id):
    data = request.get_json(force=True) or {}
    try:
        lead = lead_service.set_follow_up_status(
            current_user.tenant_id, lead_id, data.get('follow_up_status'), data.get('lost_reason')
        )
        return jsonify(lead.to_dict())
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)


# ------------------------------------------------------------------ #
#  Interactions
# ------------------------------------------------------------------ #
@leads_api_bp.route('/leads/<int:lead_id>/interactions', methods=['GET'])
@login_required
def list_interactions(lead_id):
    interactions = interaction_service.list_interactions(current_user.tenant_id, lead_id)
    return jsonify([i.to_dict() for i in interactions])


@leads_api_bp.route('/leads/<int:lead_id>/interactions', methods=['POST'])
@login_required
def create_interaction(lead_id):
    data = request.get_json(force=True) or {}
    try:
        interaction = interaction_service.log_interaction(
            tenant_id=current_user.tenant_id,
            lead_id=lead_id,
            interaction_type=data.get('interaction_type'),
            created_by=current_user.id,
            outcome=data.get('outcome'),
            notes=data.get('notes'),
            next_action_date=data.get('next_action_date'),
            qualification_score=data.get('qualification_score'),
            lost_reason=data.get('lost_reason'),
        )
        return jsonify(interaction.to_dict()), 201
    except (ValueError, LookupError) as exc:
        return _err(exc, 404 if isinstance(exc, LookupError) else 400)
    except Exception as exc:
        current_app.logger.exception('create_interaction error: %s', exc)
        return _err('Failed to log interaction', 500)
