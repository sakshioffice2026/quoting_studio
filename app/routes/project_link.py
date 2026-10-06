from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from ..services.domain import project_link_service as link

project_link_bp = Blueprint('project_link', __name__, url_prefix='/link')


def _back(default_endpoint: str, **values):
    return redirect(request.referrer or url_for(default_endpoint, **values))


# ------------------------------------------------------------------ #
#  GET /link/customers?q=
# ------------------------------------------------------------------ #
@project_link_bp.route('/customers')
@login_required
def customers():
    rows = link.search_customers(current_user.tenant_id, request.args.get('q'))
    return jsonify([c.to_dict() for c in rows])


# ------------------------------------------------------------------ #
#  GET /link/customers/<id>/projects
# ------------------------------------------------------------------ #
@project_link_bp.route('/customers/<int:customer_id>/projects')
@login_required
def customer_projects(customer_id):
    projects = link.list_customer_projects(current_user.tenant_id, customer_id)
    rows = []
    for p in projects:
        q = link.get_active_quotation(current_user.tenant_id, p.id)
        rows.append({
            'id':             p.id,
            'name':           p.display_name,
            'status':         p.status_label,
            'quotation_id':   q.id if q else None,
            'quotation_no':   q.quotation_number if q else None,
            'quotation_total': float(q.grand_total or 0) if q else 0,
        })
    return jsonify(rows)


# ------------------------------------------------------------------ #
#  POST /link/customers/<id>/projects/new
# ------------------------------------------------------------------ #
@project_link_bp.route('/customers/<int:customer_id>/projects/new', methods=['POST'])
@login_required
def new_project(customer_id):
    try:
        project = link.create_project_for_customer(
            current_user.tenant_id, customer_id, current_user.id,
            project_name=request.form.get('project_name'),
            address=request.form.get('address'),
        )
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('customers.detail', customer_id=customer_id))

    flash('Project created.', 'success')
    return redirect(url_for('projects.detail', project_id=project.id))


# ------------------------------------------------------------------ #
#  GET /link/leads/<id>/suggest-projects
# ------------------------------------------------------------------ #
@project_link_bp.route('/leads/<int:lead_id>/suggest-projects')
@login_required
def suggest_projects(lead_id):
    try:
        projects = link.suggest_projects_for_lead(current_user.tenant_id, lead_id)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify([{'id': p.id, 'name': p.display_name, 'status': p.status_label}
                    for p in projects])


# ------------------------------------------------------------------ #
#  POST /link/leads/<id>/attach
#  form: project_id (optional), new_project_name (optional)
# ------------------------------------------------------------------ #
@project_link_bp.route('/leads/<int:lead_id>/attach', methods=['POST'])
@login_required
def attach_lead(lead_id):
    try:
        project = link.attach_lead_to_project(
            current_user.tenant_id, lead_id, current_user.id,
            project_id=request.form.get('project_id', type=int),
            new_project_name=request.form.get('new_project_name'),
        )
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('leads.detail', lead_id=lead_id))

    flash(f'Lead linked to project "{project.display_name}".', 'success')
    return redirect(url_for('leads.detail', lead_id=lead_id))


# ------------------------------------------------------------------ #
#  GET /link/quotations/<id>/mergeable
# ------------------------------------------------------------------ #
@project_link_bp.route('/quotations/<int:quotation_id>/mergeable')
@login_required
def mergeable(quotation_id):
    from ..models.quotation import Quotation

    q = Quotation.query.filter_by(tenant_id=current_user.tenant_id, id=quotation_id).first()
    if not q:
        return jsonify({'error': 'Quotation not found'}), 404

    customer_id = q.project.customer_id if q.project else None
    if not customer_id:
        return jsonify([])

    rows = link.list_mergeable_quotations(current_user.tenant_id, customer_id,
                                          exclude_id=quotation_id)
    return jsonify([{
        'id':           r.id,
        'number':       r.quotation_number,
        'project_id':   r.project_id,
        'project_name': r.project.display_name if r.project else '',
        'total':        float(r.grand_total or 0),
        'items':        len(r.line_items),
    } for r in rows])


# ------------------------------------------------------------------ #
#  POST /link/quotations/<target_id>/merge
#  form: source_id
# ------------------------------------------------------------------ #
@project_link_bp.route('/quotations/<int:target_id>/merge', methods=['POST'])
@login_required
def merge_quotation(target_id):
    source_id = request.form.get('source_id', type=int)
    if not source_id:
        flash('Select a quotation to merge.', 'error')
        return redirect(url_for('quotation.detail', quotation_id=target_id))

    try:
        target = link.merge_quotations(
            current_user.tenant_id, source_id, target_id, merged_by=current_user.id
        )
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('quotation.detail', quotation_id=target_id))

    flash(f'Merged into {target.quotation_number}.', 'success')
    return redirect(url_for('quotation.detail', quotation_id=target.id))


# ------------------------------------------------------------------ #
#  POST /link/projects/<target_id>/merge
#  form: source_id
# ------------------------------------------------------------------ #
@project_link_bp.route('/projects/<int:target_id>/merge', methods=['POST'])
@login_required
def merge_project(target_id):
    source_id = request.form.get('source_id', type=int)
    if not source_id:
        flash('Select a project to merge.', 'error')
        return redirect(url_for('projects.detail', project_id=target_id))

    try:
        link.merge_projects(current_user.tenant_id, source_id, target_id)
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('projects.detail', project_id=target_id))

    flash('Projects merged.', 'success')
    return redirect(url_for('projects.detail', project_id=target_id))
