import io
import os

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, abort, send_file, current_app)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Tenant, Window
from ..models.design_approval import DesignApprovalStatus
from ..models.quotation import QuotationStatus
from ..models.share_link import ShareResource
from ..services.domain import (design_approval_service, quotation_service,
                               share_link_service as links)
from ..services.domain.pdf_quotation import generate_quotation_pdf

share_bp = Blueprint('share', __name__)

_QUOTE_HIDDEN  = {QuotationStatus.DRAFT, QuotationStatus.PENDING_DISCOUNT_APPROVAL}
_QUOTE_ACTIVE  = {QuotationStatus.SENT, QuotationStatus.NEGOTIATION}
_DESIGN_HIDDEN = {DesignApprovalStatus.DRAFT, DesignApprovalStatus.SUPERSEDED}
_DESIGN_ACTIVE = {DesignApprovalStatus.SUBMITTED, DesignApprovalStatus.APPROVAL_SENT}


def _link_payload(link):
    return {
        'url':        url_for('share.public_view', token=link.token, _external=True),
        'state':      link.state,
        'expires_at': link.expires_at.strftime('%d %b %Y') if link.expires_at else None,
        'views':      link.view_count or 0,
    }


# ================================================================== #
#  STAFF — generate / regenerate / revoke
# ================================================================== #

@share_bp.route('/share/<resource_type>/<int:resource_id>/link', methods=['POST'])
@login_required
def create_link(resource_type, resource_id):
    try:
        link = links.get_or_create(
            current_user.tenant_id, resource_type, resource_id, current_user.id
        )
    except (ValueError, LookupError) as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(_link_payload(link))


@share_bp.route('/share/<resource_type>/<int:resource_id>/regenerate', methods=['POST'])
@login_required
def regenerate_link(resource_type, resource_id):
    try:
        link = links.regenerate(
            current_user.tenant_id, resource_type, resource_id, current_user.id
        )
    except (ValueError, LookupError) as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(_link_payload(link))


@share_bp.route('/share/<resource_type>/<int:resource_id>/revoke', methods=['POST'])
@login_required
def revoke_link(resource_type, resource_id):
    if resource_type not in ShareResource.ALL:
        return jsonify({'error': 'Unsupported resource type'}), 400
    count = links.revoke(current_user.tenant_id, resource_type, resource_id)
    return jsonify({'revoked': count})


# ================================================================== #
#  PUBLIC — customer pages (no login)
# ================================================================== #

def _resolve(token):
    link = links.find_by_token(token)
    if not link or not link.is_active:
        return None, None
    resource = links.load_resource(link)
    if not resource:
        return None, None
    return link, resource


def _invalid():
    return render_template('public_link_invalid.html'), 404


@share_bp.route('/s/<token>')
def public_view(token):
    link, resource = _resolve(token)
    if not link:
        return _invalid()

    tenant = db.session.get(Tenant, link.tenant_id)

    if link.resource_type == ShareResource.QUOTATION:
        if resource.status in _QUOTE_HIDDEN:
            return render_template('public_link_invalid.html', not_ready=True), 404
        links.mark_viewed(link)
        return render_template(
            'public_quotation.html',
            token=token,
            link=link,
            tenant=tenant,
            quotation=resource,
            project=resource.project,
            can_respond=resource.status in _QUOTE_ACTIVE and not resource.is_expired,
            QuotationStatus=QuotationStatus,
        )

    if link.resource_type == ShareResource.DESIGN_APPROVAL:
        if resource.status in _DESIGN_HIDDEN:
            return render_template('public_link_invalid.html', not_ready=True), 404
        links.mark_viewed(link)
        windows = (Window.query
                   .filter_by(tenant_id=link.tenant_id, project_id=resource.project_id)
                   .order_by(Window.sequence_order, Window.id)
                   .all())
        return render_template(
            'public_design_approval.html',
            token=token,
            link=link,
            tenant=tenant,
            approval=resource,
            project=resource.project,
            windows=windows,
            can_respond=resource.status in _DESIGN_ACTIVE and not resource.is_expired,
            DesignApprovalStatus=DesignApprovalStatus,
        )

    return _invalid()


# ---- Quotation actions -------------------------------------------- #

@share_bp.route('/s/<token>/accept', methods=['POST'])
def public_accept(token):
    link, q = _resolve(token)
    if not link or link.resource_type != ShareResource.QUOTATION:
        return _invalid()
    try:
        quotation_service.accept_quotation(
            link.tenant_id, q.id,
            acceptance_method='link',
            accepted_by_name=(request.form.get('name') or '').strip() or None,
        )
        links.mark_responded(link)
        flash('Thank you — the quotation has been accepted.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('share.public_view', token=token))


@share_bp.route('/s/<token>/reject', methods=['POST'])
def public_reject(token):
    link, q = _resolve(token)
    if not link or link.resource_type != ShareResource.QUOTATION:
        return _invalid()
    reason = (request.form.get('reason') or '').strip() or 'Declined by customer via shared link'
    try:
        quotation_service.mark_lost(link.tenant_id, q.id, f'Customer: {reason}')
        links.mark_responded(link)
        flash('Your response has been recorded.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('share.public_view', token=token))


@share_bp.route('/s/<token>/pdf')
def public_pdf(token):
    link, q = _resolve(token)
    if not link or link.resource_type != ShareResource.QUOTATION:
        return _invalid()
    if q.status in _QUOTE_HIDDEN:
        abort(404)

    if q.pdf_path:
        full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], q.pdf_path)
        if os.path.exists(full_path):
            return send_file(full_path, mimetype='application/pdf',
                             as_attachment=True, download_name=f'{q.quotation_number}.pdf')

    try:
        tenant = db.session.get(Tenant, link.tenant_id)
        pdf_bytes = generate_quotation_pdf(quotation=q, project=q.project, tenant=tenant)
    except Exception as exc:
        current_app.logger.exception('public_pdf error quotation=%s: %s', q.id, exc)
        abort(500)

    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=f'{q.quotation_number}.pdf')


# ---- Design approval actions -------------------------------------- #

@share_bp.route('/s/<token>/approve', methods=['POST'])
def public_approve(token):
    link, approval = _resolve(token)
    if not link or link.resource_type != ShareResource.DESIGN_APPROVAL:
        return _invalid()
    if approval.status not in _DESIGN_ACTIVE:
        flash('This design can no longer be approved from this link.', 'error')
        return redirect(url_for('share.public_view', token=token))

    name = (request.form.get('name') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    signoff = f'Approved by {name} via shared link' if name else 'Approved via shared link'
    if notes:
        signoff = f'{signoff}: {notes}'
    try:
        design_approval_service.approve(
            link.tenant_id, approval.id, None, customer_signoff_notes=signoff
        )
        links.mark_responded(link)
        flash('Thank you — the design has been approved.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('share.public_view', token=token))


@share_bp.route('/s/<token>/request-revision', methods=['POST'])
def public_request_revision(token):
    link, approval = _resolve(token)
    if not link or link.resource_type != ShareResource.DESIGN_APPROVAL:
        return _invalid()
    if approval.status not in _DESIGN_ACTIVE:
        flash('Changes can no longer be requested from this link.', 'error')
        return redirect(url_for('share.public_view', token=token))

    reason = (request.form.get('reason') or '').strip()
    try:
        design_approval_service.request_revision(
            link.tenant_id, approval.id, None, f'Customer: {reason}' if reason else ''
        )
        links.mark_responded(link)
        flash('Your change request has been sent.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('share.public_view', token=token))
