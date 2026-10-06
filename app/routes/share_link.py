from urllib.parse import quote as _urlquote

from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required, current_user

from ..models import Tenant
from ..models.share_link import ShareLinkType
from ..models.quotation import QuotationStatus
from ..models.design_approval import DesignApprovalStatus
from ..services.domain import (
    share_link_service,
    quotation_service,
    design_approval_service,
    visual_feedback_service,
)

share_link_bp = Blueprint('share_link', __name__, url_prefix='/share-links')

_TYPE_SLUGS = {
    'quotation':       ShareLinkType.QUOTATION,
    'design-approval': ShareLinkType.DESIGN_APPROVAL,
    'visualiser':      ShareLinkType.VISUALISER,
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


def _visualiser_messages(quotation_id: int, url: str) -> dict:
    """Ready-to-send WhatsApp and email text for a visualiser link."""
    tenant_id = current_user.tenant_id
    q = quotation_service.get_quotation(tenant_id, quotation_id)
    project = q.project if q else None
    customer = getattr(project, 'customer', None) if project else None

    name = ((getattr(customer, 'name', None)
             or getattr(project, 'customer_name', None) or '')).strip()
    phone = ''.join(ch for ch in (getattr(customer, 'phone', None) or '') if ch.isdigit())
    email = (getattr(customer, 'email', None) or '').strip()
    tenant = Tenant.query.get(tenant_id)
    company = tenant.name if tenant else ''

    greeting = f'Hi {name},' if name else 'Hello,'
    body = (
        f'{greeting}\n\n'
        'Here is the preview of your windows and doors on your home photo. '
        'You can look at each item, tap "Looks good" or "Request a change", '
        'or approve everything in one go:\n\n'
        f'{url}\n\n'
        'This link is private to you and expires automatically.\n\n'
        f'Thank you,\n{company}'.rstrip()
    )
    subject = f'Your window and door preview{" - " + company if company else ""}'

    whatsapp = f'https://wa.me/{phone}?text={_urlquote(body)}' if phone \
        else f'https://wa.me/?text={_urlquote(body)}'
    mailto = (f'mailto:{_urlquote(email)}?subject={_urlquote(subject)}'
              f'&body={_urlquote(body)}')

    return {
        'message': {
            'whatsapp_text': body,
            'whatsapp_url':  whatsapp,
            'email_subject': subject,
            'email_body':    body,
            'email_url':     mailto,
            'has_phone':     bool(phone),
            'has_email':     bool(email),
        },
    }


@share_link_bp.route('/<slug>/<int:resource_id>/generate', methods=['POST'])
@login_required
def generate(slug, resource_id):
    resource_type = _TYPE_SLUGS.get(slug)
    if not resource_type:
        return jsonify({'ok': False, 'error': 'Unsupported link type.'}), 404

    data = request.get_json(silent=True) or {}
    force_new = bool(data.get('force_new'))
    ttl_days = data.get('ttl_days')
    try:
        ttl_days = int(ttl_days) if ttl_days else None
    except (TypeError, ValueError):
        ttl_days = None

    if resource_type == ShareLinkType.VISUALISER:
        try:
            link = share_link_service.create_visualiser_link(
                tenant_id=current_user.tenant_id,
                quotation_id=resource_id,
                created_by=current_user.id,
                ttl_days=ttl_days,
                force_new=force_new,
            )
        except LookupError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        payload = _payload(link)
        payload.update(_visualiser_messages(resource_id, payload['url']))
        return jsonify(payload)

    ok, error = _check_resource(resource_type, resource_id)
    if not ok:
        return jsonify({'ok': False, 'error': error}), 400

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


# ------------------------------------------------------------------ #
#  Visualiser feedback inbox (staff side)
# ------------------------------------------------------------------ #
@share_link_bp.route('/feedback/<int:quotation_id>')
@login_required
def feedback_inbox(quotation_id):
    tenant_id = current_user.tenant_id
    if not quotation_service.get_quotation(tenant_id, quotation_id):
        return jsonify({'ok': False, 'error': 'Quotation not found.'}), 404

    show_all = request.args.get('all') == '1'
    state = visual_feedback_service.summary(tenant_id, quotation_id)
    link = share_link_service.get_visualiser_link(tenant_id, quotation_id)
    return jsonify({
        'ok':            True,
        'open_count':    state['open_count'],
        'all_approved':  state['all_approved'],
        'ready_to_lock': state['ready_to_lock'],
        'items': [
            {
                'line_id':      s['line_id'],
                'label':        s['label'],
                'approved':     s['approved'],
                'needs_review': s['needs_review'],
                'open_count':   len(s['open_requests']),
            }
            for s in state['items']
        ],
        'requests': visual_feedback_service.inbox(
            tenant_id, quotation_id, only_open=not show_all),
        'link': link.to_dict() if link else None,
    })


@share_link_bp.route('/feedback/<int:feedback_id>/resolve', methods=['POST'])
@login_required
def feedback_resolve(feedback_id):
    data = request.get_json(silent=True) or {}
    try:
        row = visual_feedback_service.resolve_request(
            current_user.tenant_id, feedback_id, current_user.id,
            note=data.get('note'))
    except LookupError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({
        'ok':         True,
        'feedback':   row.to_dict(),
        'open_count': visual_feedback_service.open_request_count(
            current_user.tenant_id, row.quotation_id),
    })