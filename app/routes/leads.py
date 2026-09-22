from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models import User
from ..models.lead import LeadStatus, FollowUpStatus
from ..services.domain import lead_service, interaction_service, preliminary_selection_service, survey_service
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


@leads_bp.route('/timeline')
@login_required
def timeline_index():
    """Sidebar shortcut — pick any lead and open its project timeline."""
    status = request.args.get('status') or None
    try:
        leads = lead_service.list_leads(current_user.tenant_id, status=status)
    except Exception as exc:
        current_app.logger.exception('Timeline index error: %s', exc)
        leads = []
    return render_template('timeline_index.html', leads=leads, status_filter=status, LeadStatus=LeadStatus)


@leads_bp.route('/leads/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        try:
            lead = lead_service.create_lead(
                tenant_id=current_user.tenant_id,
                customer_name=request.form.get('customer_name', ''),
                project_name=(request.form.get('project_name') or '').strip() or None,
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

    from ..repositories import requirement_template_repo
    from ..services.domain import requirement_template_service
    template_response = requirement_template_repo.get_response_by_lead(current_user.tenant_id, lead_id)
    template_summary = (
        requirement_template_service.get_summary(template_response)
        if template_response and template_response.is_submitted else None
    )

    return render_template(
        'lead_detail.html', lead=lead, interactions=interactions, team=team, presel=presel,
        template_response=template_response, template_summary=template_summary,
    )


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


@leads_bp.route('/leads/<int:lead_id>/flow')
@login_required
def flow(lead_id):
    lead = lead_service.get_lead(current_user.tenant_id, lead_id)
    if not lead:
        flash('Lead not found.', 'error')
        return redirect(url_for('leads.index'))

    from ..services.domain import design_approval_service

    presel = preliminary_selection_service.get_by_lead(current_user.tenant_id, lead_id)
    survey = survey_service.get_by_lead(current_user.tenant_id, lead_id)
    design_approval = (design_approval_service.get_latest_for_project(current_user.tenant_id, lead.project_id)
                        if lead.project_id else None)

    def not_started():
        return {'implemented': False, 'status_label': 'Not started', 'group': 'pending', 'url': None}

    stages = [
        {
            'number': 1, 'key': 'lead', 'group': 'lead',
            'label': 'Lead Generation', 'title': 'New Enquiry Captured',
            'subtitle': 'Source Channel, Customer Info, Rough Requirement',
            'implemented': True,
            'status_label': lead.status,
            'url': url_for('leads.detail', lead_id=lead.id),
        },
        {
            'number': 2, 'key': 'follow_up', 'group': 'lead',
            'label': 'Follow-Up', 'title': 'Contact & Qualification',
            'subtitle': 'First Contact, Budget Check, Site Visit Booked',
            'implemented': True,
            'status_label': lead.follow_up_status or 'Not started',
            'url': url_for('leads.detail', lead_id=lead.id),
        },
        {
            'number': 3, 'key': 'presel', 'group': 'presel',
            'label': 'Preliminary Selection', 'title': 'Catalog & Style Walkthrough',
            'subtitle': 'Shortlist Ranges, Ballpark Price, Survey Req.',
            **({
                'implemented': True,
                'status_label': presel.status,
                'url': url_for('presel.detail', presel_id=presel.id),
            } if presel else not_started()),
        },
        {
            'number': 4, 'key': 'survey', 'group': 'presel',
            'label': 'Survey', 'title': 'On-Site Measurement',
            'subtitle': 'Accurate Dimensions, Site Conditions, Photos',
            **({
                'implemented': True,
                'status_label': survey.status,
                'url': url_for('survey.detail', survey_id=survey.id),
            } if survey else not_started()),
        },
        {
            'number': 5, 'key': 'design', 'group': 'design',
            'label': 'Design & Specs', 'title': 'Configurator & BOM',
            'subtitle': 'Select Profiles, Generate Drawings, BOM',
            **({
                'implemented': True,
                'status_label': design_approval.status_label,
                'url': url_for('design_approval.detail', approval_id=design_approval.id),
            } if design_approval else (
                {
                    'implemented': True,
                    'status_label': 'In Progress',
                    'url': url_for('projects.detail', project_id=lead.project_id),
                } if lead.project_id else not_started()
            )),
        },
        {
            'number': 6, 'key': 'approval', 'group': 'design',
            'label': 'Customer Approval', 'title': 'Design Sign-off',
            'subtitle': 'Share Drawings & BOM, Get Customer Approval',
            **({
                'implemented': True,
                'status_label': design_approval.status_label,
                'url': url_for('design_approval.detail', approval_id=design_approval.id),
            } if design_approval and design_approval.status in (
                'DESIGN-SUBMITTED', 'DESIGN-APPROVED', 'DESIGN-REVISION_REQUESTED'
            ) else not_started()),
        },
        {
            'number': 7, 'key': 'quotation', 'group': 'design',
            'label': 'Quotation', 'title': 'Formal Pricing',
            'subtitle': 'Line-Item Quote, Terms, Validity',
            **not_started(),
        },
        {
            'number': 8, 'key': 'order', 'group': 'design',
            'label': 'Order', 'title': 'Order Confirmation',
            'subtitle': 'PO / Order Acceptance, Production Handoff',
            **not_started(),
        },
        {
            'number': 9, 'key': 'advance_payment', 'group': 'payment',
            'label': 'Advance Payment', 'title': 'Initial Milestone',
            'subtitle': 'Invoice (40-50%), Collect Payment, Reconcile',
            **not_started(),
        },
        {
            'number': 10, 'key': 'payment_journey', 'group': 'payment',
            'label': 'Payment Journey', 'title': 'Milestone Tracking',
            'subtitle': 'Progress Invoices, Balance Due, Reconciliation',
            **not_started(),
        },
        {
            'number': 11, 'key': 'manufacturing', 'group': 'manufacturing',
            'label': 'Manufacturing', 'title': 'Shop Floor Production',
            'subtitle': 'Cutting, Machining, Assembly, QC',
            **not_started(),
        },
        {
            'number': 12, 'key': 'delivery', 'group': 'manufacturing',
            'label': 'Delivery', 'title': 'Dispatch & Transport',
            'subtitle': 'Packing List, Dispatch, Site Delivery',
            **not_started(),
        },
        {
            'number': 13, 'key': 'installation', 'group': 'amc',
            'label': 'Installation', 'title': 'On-Site Fit-out',
            'subtitle': 'Install, Snag List, Handover',
            **not_started(),
        },
        {
            'number': 14, 'key': 'amc', 'group': 'amc',
            'label': 'AMC', 'title': 'Warranty & Maintenance',
            'subtitle': 'Warranty Start, Schedule Service, Renewals',
            **not_started(),
        },
    ]

    # ---- dates + hover details per stage ------------------------------
    def fmt_d(d):
        return d.strftime('%d %b %Y') if d else None

    def fmt_dt(d):
        return d.strftime('%d %b %Y, %H:%M') if d else None

    interactions = lead.interactions.all()
    first_contact = interactions[0] if interactions else None
    last_contact = interactions[-1] if interactions else None

    infos = {}

    infos['lead'] = {
        'date_label': 'Created',
        'date': fmt_d(lead.created_at),
        'tip': [
            ('Current status', '%s (%s)' % (lead.status_label, lead.status)),
            ('Created', fmt_dt(lead.created_at)),
            ('Last updated', fmt_dt(lead.updated_at)),
            ('Assigned to', getattr(lead.assignee, 'full_name', None) if lead.assignee else None),
            ('Source', lead.source_channel),
        ],
    }

    if lead.follow_up_status or interactions:
        infos['follow_up'] = {
            'date_label': 'First contact',
            'date': fmt_d(first_contact.created_at) if first_contact else None,
            'tip': [
                ('Current status', '%s (%s)' % (lead.follow_up_status_label or 'In progress',
                                                lead.follow_up_status or 'FUP-IN_PROGRESS')),
                ('First contact', fmt_dt(first_contact.created_at) if first_contact else None),
                ('Last contact', fmt_dt(last_contact.created_at) if last_contact else None),
                ('Interactions logged', str(len(interactions))),
                ('Next action', fmt_d(last_contact.next_action_date) if last_contact else None),
                ('Qualification', last_contact.qualification_score if last_contact else None),
                ('Lost reason', lead.lost_reason),
            ],
        }

    if presel:
        infos['presel'] = {
            'date_label': 'Started',
            'date': fmt_d(presel.created_at),
            'tip': [
                ('Current status', '%s (%s)' % (presel.status_label, presel.status)),
                ('Started', fmt_dt(presel.created_at)),
                ('Last updated', fmt_dt(presel.updated_at)),
                ('Rough openings', str(presel.rough_opening_count)),
            ],
        }

    if survey:
        infos['survey'] = {
            'date_label': 'Scheduled' if survey.scheduled_date else 'Created',
            'date': fmt_d(survey.scheduled_date) or fmt_d(survey.created_at),
            'tip': [
                ('Current status', '%s (%s)' % (survey.status_label, survey.status)),
                ('Scheduled', fmt_d(survey.scheduled_date)),
                ('Completed', fmt_d(survey.completed_date)),
                ('Surveyor', survey.surveyor_name),
                ('Openings measured', str(survey.opening_count)),
                ('Last updated', fmt_dt(survey.updated_at)),
            ],
        }

    if design_approval:
        infos['design'] = {
            'date_label': 'Created',
            'date': fmt_d(design_approval.created_at),
            'tip': [
                ('Current status', '%s (%s)' % (design_approval.status_label, design_approval.status)),
                ('Revision', 'Rev %s' % design_approval.revision_number),
                ('Created', fmt_dt(design_approval.created_at)),
                ('Last updated', fmt_dt(design_approval.updated_at)),
            ],
        }
        if design_approval.approved_at:
            appr_label, appr_date = 'Approved', design_approval.approved_at
        elif design_approval.revision_requested_at:
            appr_label, appr_date = 'Revision requested', design_approval.revision_requested_at
        else:
            appr_label, appr_date = 'Sent', design_approval.submitted_at
        infos['approval'] = {
            'date_label': appr_label,
            'date': fmt_d(appr_date),
            'tip': [
                ('Current status', '%s (%s)' % (design_approval.status_label, design_approval.status)),
                ('Sent to customer', fmt_dt(design_approval.submitted_at)),
                ('Approved', fmt_dt(design_approval.approved_at)),
                ('Revision requested', fmt_dt(design_approval.revision_requested_at)),
                ('Revision reason', design_approval.revision_requested_reason),
                ('Sign-off notes', design_approval.customer_signoff_notes),
            ],
        }
    elif lead.project_id:
        infos['design'] = {
            'date_label': 'In progress',
            'date': None,
            'tip': [('Current status', 'In progress')],
        }

    # ---- Sections 7–12 (Quotation → Delivery) from live project data ----
    try:
        from ..services.domain import flow_service
        downstream = flow_service.build_downstream(current_user.tenant_id, lead.project_id)
    except Exception as exc:
        current_app.logger.exception('Flow downstream stages error: %s', exc)
        downstream = {}

    downstream_groups = {
        'quotation': 'design', 'order': 'design',
        'advance_payment': 'payment', 'payment_journey': 'payment',
        'manufacturing': 'manufacturing', 'delivery': 'manufacturing',
    }
    for s in stages:
        d = downstream.get(s['key'])
        if not d:
            continue
        s['implemented']  = True
        s['group']        = downstream_groups.get(s['key'], s['group'])
        s['status_label'] = d['status_label']
        s['url']          = d['url']
        infos[s['key']] = {
            'date_label': d['date_label'],
            'date':       d['date'],
            'tip':        d['tip'],
        }

    for s in stages:
        info = infos.get(s['key']) if s['implemented'] else None
        if info:
            s['date'] = info['date']
            s['date_label'] = info['date_label']
            s['tip'] = [(k, v) for k, v in info['tip'] if v]
        else:
            s['date'] = None
            s['date_label'] = None
            s['tip'] = [('Current status', s['status_label'])]

    return render_template('project_timeline.html', lead=lead, stages=stages)