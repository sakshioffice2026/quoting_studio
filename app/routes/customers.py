from flask import Blueprint, render_template, current_app, request
from flask_login import login_required, current_user

from ..services.domain import customer_service

customers_bp = Blueprint('customers', __name__)


@customers_bp.route('/customers')
@login_required
def index():
    search = request.args.get('q') or None
    try:
        customers = customer_service.list_customers(current_user.tenant_id, search=search)
    except Exception as exc:
        current_app.logger.exception('Customers page error: %s', exc)
        customers = []
    return render_template('customers.html', customers=customers)


@customers_bp.route('/customers/<int:customer_id>')
@login_required
def detail(customer_id):
    customer = customer_service.get_customer(current_user.tenant_id, customer_id)
    return render_template('customer_detail.html', customer=customer)
