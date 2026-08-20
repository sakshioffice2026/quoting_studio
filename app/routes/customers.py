from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from ..models import Project, ProjectStatus

customers_bp = Blueprint('customers', __name__)

@customers_bp.route('/customers')
@login_required
def index():
    try:
        projects = (Project.query
                    .filter_by(tenant_id=current_user.tenant_id)
                    .order_by(Project.customer_name)
                    .all())
        # group by customer name
        customers = {}
        for p in projects:
            name = p.customer_name
            if name not in customers:
                customers[name] = {
                    'name':    name,
                    'address': p.address or '',
                    'projects': [],
                }
            customers[name]['projects'].append(p)

        customer_list = sorted(customers.values(), key=lambda c: c['name'])
        return render_template('customers.html', customers=customer_list)
    except Exception as exc:
        current_app.logger.exception('Customers page error: %s', exc)
        return render_template('customers.html', customers=[])
