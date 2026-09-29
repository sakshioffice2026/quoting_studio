from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required, current_user

from ..models.share_link import ShareLinkType
from ..models.quotation import QuotationStatus
from ..models.design_approval import DesignApprovalStatus
from ..services.domain import (
    share_link_service,
    quotation_service,
    design_approval_service,
)

share_link_bp = Blueprint('share_link', __name__, url_prefix='/share-links')

_TYPE_SLUGS = {
    'quotation':       ShareLinkType.QUOTATION,
    'design-approval': ShareLinkType.DESIGN_APPROVAL,
}

_QUOTE_SHAREABLE = {
    QuotationStatus.SENT,
    QuotationStatus.NEGOTIATION,
    QuotationStatus.ACCEPTED,
}
_DESIGN_SHAREABLE = {
    DesignApprovalStatus.APPROVAL_SENT,
    DesignApprovalStatus.APPROVED,
}


def _check_resource(resource_type: str, resource_id: int):
    """Returns (ok, error_message). Confirms the record belongs to the
    current tenant and is in a state the customer is allowed to see."""
    tenant_id = current_user.tenant_id

    if resource_type == ShareLinkType.QUOTATION:
        q = quotation_service.get_quotation(tenant_id, resource_id)
        if not q:
            return False, 'Quotation not found.'
        if q.status not in _QUOTE_SHAREABLE:
            return False, 'Send the quotation to the customer first, then copy the link.'
        return True, None

    if resource_type == ShareLinkType.DESIGN_APPROVAL:
        a = design_approval_service.get_approval(tenant_id, resource_id)
        if not a:
            return False, 'Design approval not found.'
        if a.status not in _DESIGN_SHAREABLE:
            return False, 'Send the design to the customer first, then copy the link.'
        return True, None

    return False, 'Unsupported link type.'


def _payload(link):
    return {
        'ok': True,
        'url': url_for('public_share.view', token=link.token, _external=True),
        'link': link.to_dict(),
    }


@share_link_bp.route('/<slug>/<int:resource_id>/generate', methods=['POST'])
@login_required
def generate(slug, resource_id):
    resource_type = _TYPE_SLUGS.get(slug)
    if not resource_type:
        return jsonify({'ok': False, 'error': 'Unsupported link type.'}), 404

    ok, error = _check_resource(resource_type, resource_id)
    if not ok:
        return jsonify({'ok': False, 'error': error}), 400

    data = request.get_json(silent=True) or {}
    force_new = bool(data.get('force_new'))
    ttl_days = data.get('ttl_days')
    try:
        ttl_days = int(ttl_days) if ttl_days else None
    except (TypeError, ValueError):
        ttl_days = None

    link = share_link_service.get_or_create_link(
        tenant_id=current_user.tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        created_by=current_user.id,
        ttl_days=ttl_days,
        force_new=force_new,
    )
    return jsonify(_payload(link))


@share_link_bp.route('/<slug>/<int:resource_id>/status')
@login_required
def status(slug, resource_id):
    resource_type = _TYPE_SLUGS.get(slug)
    if not resource_type:
        return jsonify({'ok': False, 'error': 'Unsupported link type.'}), 404

    link = share_link_service.get_latest(current_user.tenant_id, resource_type, resource_id)
    if not link:
        return jsonify({'ok': True, 'link': None})
    return jsonify({'ok': True, 'link': link.to_dict()})


@share_link_bp.route('/<int:link_id>/revoke', methods=['POST'])
@login_required
def revoke(link_id):
    try:
        link = share_link_service.revoke(current_user.tenant_id, link_id)
    except LookupError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404
    return jsonify({'ok': True, 'link': link.to_dict()})


@share_link_bp.route('/<int:link_id>/extend', methods=['POST'])
@login_required
def extend(link_id):
    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get('days')) if data.get('days') else None
    except (TypeError, ValueError):
        days = None
    try:
        link = share_link_service.extend(current_user.tenant_id, link_id, days)
    except LookupError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'link': link.to_dict()})
