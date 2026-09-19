from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models import User
from ..models.lead import LeadStatus, FollowUpStatus
from ..services.domain import lead_service, interaction_service, preliminary_selection_service
leads_bp = Blueprint('leads', __name__)


@leads_bp.route('/leads')
@login_required
def index():
    status = request.args.get('status') or None
    try:
        leads = lead_service.list_leads(current_user.tenant_id, status=status)
    except Exception as exc:
        current_app.logger.exception('Leads index error: %s', exc)
        leads = []
    return render_template('leads.html', leads=leads, status_filter=status, LeadStatus=LeadStatus)


@leads_bp.route('/leads/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        try:
            lead = lead_service.create_lead(
                tenant_id=current_user.tenant_id,
                customer_name=request.form.get('customer_name', ''),
                phone=request.form.get('phone') or None,
                email=request.form.get('email') or None,
                source_channel=request.form.get('source_channel') or 'website',
                project_city=request.form.get('project_city') or None,
                product_interest=request.form.get('product_interest') or None,
            )
            flash(f'Lead captured ({lead.status_label}).', 'success')
            return redirect(url_for('leads.detail', lead_id=lead.id))
        except ValueError as exc:
            flash(str(exc), 'error')
    return render_template('lead_new.html')


@leads_bp.route('/leads/<int:lead_id>')
@login_required
def detail(lead_id):
    lead = lead_service.get_lead(current_user.tenant_id, lead_id)
    if not lead:
        flash('Lead not found.', 'error')
        return redirect(url_for('leads.index'))
    interactions = interaction_service.list_interactions(current_user.tenant_id, lead_id)
    team = User.query.filter_by(tenant_id=current_user.tenant_id, is_active=True).all()
    presel = preliminary_selection_service.get_by_lead(current_user.tenant_id, lead_id)
    return render_template('lead_detail.html', lead=lead, interactions=interactions, team=team, presel=presel)


@leads_bp.route('/leads/<int:lead_id>/assign', methods=['POST'])
@login_required
def assign(lead_id):
    try:
        user_id = int(request.form.get('assigned_to'))
        lead_service.assign_lead(current_user.tenant_id, lead_id, user_id)
        flash('Lead assigned.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/leads/<int:lead_id>/follow-up', methods=['POST'])
@login_required
def follow_up(lead_id):
    try:
        lead_service.set_follow_up_status(current_user.tenant_id, lead_id, FollowUpStatus.IN_PROGRESS)
        flash('Follow-up started.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/leads/<int:lead_id>/qualify', methods=['POST'])
@login_required
def qualify(lead_id):
    try:
        lead_service.qualify_lead(current_user.tenant_id, lead_id)
        flash('Lead marked as qualified.', 'success')
    except LookupError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/leads/<int:lead_id>/nurture', methods=['POST'])
@login_required
def nurture(lead_id):
    try:
        lead_service.set_follow_up_status(current_user.tenant_id, lead_id, FollowUpStatus.NURTURE)
        flash('Lead moved to nurture.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/leads/<int:lead_id>/lost', methods=['POST'])
@login_required
def lost(lead_id):
    try:
        reason = request.form.get('lost_reason') or ''
        lead_service.set_follow_up_status(current_user.tenant_id, lead_id, FollowUpStatus.LOST, reason)
        flash('Lead closed as lost.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/leads/<int:lead_id>/interactions', methods=['POST'])
@login_required
def add_interaction(lead_id):
    try:
        interaction_service.log_interaction(
            tenant_id=current_user.tenant_id,
            lead_id=lead_id,
            interaction_type=request.form.get('interaction_type'),
            created_by=current_user.id,
            outcome=request.form.get('outcome') or None,
            notes=request.form.get('notes') or None,
            next_action_date=request.form.get('next_action_date') or None,
            qualification_score=request.form.get('qualification_score') or None,
            lost_reason=request.form.get('lost_reason') or None,
        )
        flash('Interaction logged.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('leads.detail', lead_id=lead_id))
