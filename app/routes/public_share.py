import io
import json
import os
import time
from collections import defaultdict, deque

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, current_app, abort)

from ..extensions import db
from ..models import Tenant, Window
from ..models.visualisation import Visualisation
from ..models.share_link import ShareLinkType
from ..models.quotation import QuotationStatus
from ..models.design_approval import DesignApprovalStatus
from ..services.domain import (
    share_link_service,
    quotation_service,
    design_approval_service,
    visual_feedback_service,
)
from ..services.domain.pdf_quotation import generate_quotation_pdf
from ..services.domain import design_render_service

public_share_bp = Blueprint('public_share', __name__, url_prefix='/s')


@public_share_bp.after_request
def _private_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _unavailable(link, reason: str):
    return render_template('public_share/unavailable.html', link=link, reason=reason), 410


def _resolve(token: str):
    """Returns (link, error_response). Exactly one of them is None."""
    link = share_link_service.get_by_token(token)
    if not link:
        abort(404)
    if link.is_revoked:
        return None, _unavailable(link, 'This link is no longer active. Please ask for a new one.')
    if link.is_expired:
        return None, _unavailable(link, 'This link has expired. Please ask for a new one.')
    return link, None


# ------------------------------------------------------------------ #
#  GET /s/<token>
# ------------------------------------------------------------------ #
@public_share_bp.route('/<token>')
def view(token):
    link, err = _resolve(token)
    if err:
        return err

    tenant = Tenant.query.get(link.tenant_id)

    if link.resource_type == ShareLinkType.QUOTATION:
        q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
        if not q or q.status in (QuotationStatus.DRAFT, QuotationStatus.PENDING_DISCOUNT_APPROVAL):
            abort(404)
        share_link_service.record_open(link)
        return render_template(
            'public_share/quotation.html',
            link=link, quotation=q, project=q.project, tenant=tenant,
            QuotationStatus=QuotationStatus,
        )

    if link.resource_type == ShareLinkType.DESIGN_APPROVAL:
        approval = design_approval_service.get_approval(link.tenant_id, link.resource_id)
        if not approval or approval.status in (
            DesignApprovalStatus.DRAFT, DesignApprovalStatus.SUBMITTED
        ):
            abort(404)
        if approval.is_expired:
            design_approval_service.expire_approval(link.tenant_id, approval.id)
            approval = design_approval_service.get_approval(link.tenant_id, link.resource_id)
        share_link_service.record_open(link)
        drawings = design_render_service.build_drawings(approval)
        return render_template(
            'public_share/design.html',
            link=link, approval=approval, project=approval.project, tenant=tenant,
            drawings=drawings,
            DesignApprovalStatus=DesignApprovalStatus,
        )

    if link.resource_type == ShareLinkType.VISUALISER:
        q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
        if not q:
            abort(404)
        share_link_service.record_open(link)
        state = visual_feedback_service.summary(link.tenant_id, q.id)
        return render_template(
            'public_share/visualiser.html',
            link=link, quotation=q, project=q.project, tenant=tenant,
            items=_visual_items(q, state), state=state,
            can_respond=q.status not in _VISUAL_CLOSED,
            currency=_CURRENCY,
            QuotationStatus=QuotationStatus,
        )

    abort(404)


# ------------------------------------------------------------------ #
#  Visualiser (customer preview) helpers
# ------------------------------------------------------------------ #
_CURRENCY = '$'
_VISUAL_CLOSED = set(QuotationStatus.TERMINAL) | {QuotationStatus.EXPIRED}

# simple in-process throttle for customer actions on a link
_THROTTLE_MAX = 30
_THROTTLE_WINDOW = 600  # seconds
_hits = defaultdict(deque)


def _throttled(token: str) -> bool:
    now = time.time()
    bucket = _hits[token]
    while bucket and now - bucket[0] > _THROTTLE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _THROTTLE_MAX:
        return True
    bucket.append(now)
    return False


def _visual_link(token: str):
    """Resolve an active visualiser link, or (None, error_response)."""
    link, err = _resolve(token)
    if err:
        return None, err
    if link.resource_type != ShareLinkType.VISUALISER:
        abort(404)
    return link, None


def _item_render_svg(item: dict, uid: str):
    """Clean drawing of the saved design, used when no photo render exists."""
    raw = item.get('design_json')
    width, height = item.get('width_mm'), item.get('height_mm')
    if not raw or not width or not height:
        return None
    try:
        design = json.loads(raw) if isinstance(raw, str) else raw
        return design_render_service.render_svg(design, float(width), float(height), uid)
    except Exception:
        return None


def _visual_items(q, state) -> list[dict]:
    by_line = {s['line_id']: s for s in state['items']}

    window_ids = set()
    for item in q.line_items:
        if item.get('window_id') is not None:
            try:
                window_ids.add(int(item['window_id']))
            except (TypeError, ValueError):
                pass

    rendered = set()
    if window_ids:
        owned = {w.id for w in Window.query.filter(
            Window.id.in_(window_ids), Window.project_id == q.project_id).all()}
        for vis in Visualisation.query.filter(Visualisation.window_id.in_(owned)).all():
            if vis.rendered_path:
                rendered.add(vis.window_id)

    result = []
    for index, item in enumerate(q.line_items):
        lid = visual_feedback_service.line_key(item, index)
        slot = by_line.get(lid, {})
        wid = item.get('window_id')
        try:
            has_photo = wid is not None and int(wid) in rendered
        except (TypeError, ValueError):
            has_photo = False
        result.append({
            'line_id':       lid,
            'label':         item.get('label') or 'Item',
            'material':      item.get('material'),
            'width_mm':      item.get('width_mm'),
            'height_mm':     item.get('height_mm'),
            'qty':           item.get('qty') or 1,
            'amount':        item.get('amount'),
            'notes':         item.get('notes'),
            'has_photo':     has_photo,
            'svg':           None if has_photo else _item_render_svg(item, f'v{lid}'),
            'approved':      slot.get('approved', False),
            'needs_review':  slot.get('needs_review', False),
            'open_requests': slot.get('open_requests', []),
            'thread':        slot.get('thread', []),
        })
    return result


def _back(token: str, line_id=None):
    anchor = f'#item-{line_id}' if line_id is not None else ''
    return redirect(url_for('public_share.view', token=token) + anchor)


# ------------------------------------------------------------------ #
#  Visualiser actions (view / approve / comment only)
# ------------------------------------------------------------------ #
@public_share_bp.route('/<token>/visual/image/<int:line_id>')
def visual_image(token, line_id):
    link, err = _visual_link(token)
    if err:
        return err

    q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
    if not q:
        abort(404)

    item = None
    for index, candidate in enumerate(q.line_items):
        if visual_feedback_service.line_key(candidate, index) == line_id:
            item = candidate
            break
    if not item or item.get('window_id') is None:
        abort(404)

    try:
        window_id = int(item['window_id'])
    except (TypeError, ValueError):
        abort(404)

    window = Window.query.filter_by(id=window_id, project_id=q.project_id).first()
    if not window:
        abort(404)

    vis = (Visualisation.query.filter_by(window_id=window_id)
           .order_by(Visualisation.created_at.desc()).first())
    if not vis or not vis.rendered_path:
        abort(404)

    base = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.realpath(os.path.join(base, vis.rendered_path))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        abort(404)
    return send_file(full, mimetype='image/png')


@public_share_bp.route('/<token>/visual/approve', methods=['POST'])
def visual_approve(token):
    link, err = _visual_link(token)
    if err:
        return err
    if _throttled(token):
        flash('Too many actions in a short time. Please try again in a few minutes.', 'error')
        return _back(token)

    name = (request.form.get('author_name') or '').strip()
    line_raw = request.form.get('line_id')
    try:
        if line_raw in (None, '', 'all'):
            visual_feedback_service.approve_all(
                link.tenant_id, link.resource_id, share_link=link, author_name=name)
            flash('Thank you! Everything has been approved.', 'success')
            return _back(token)
        line_id = int(line_raw)
        visual_feedback_service.approve_item(
            link.tenant_id, link.resource_id, line_id, share_link=link, author_name=name)
        flash('Thank you! This item has been approved.', 'success')
        return _back(token, line_id)
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return _back(token)


@public_share_bp.route('/<token>/visual/comment', methods=['POST'])
def visual_comment(token):
    link, err = _visual_link(token)
    if err:
        return err
    if _throttled(token):
        flash('Too many actions in a short time. Please try again in a few minutes.', 'error')
        return _back(token)

    name = (request.form.get('author_name') or '').strip()
    comment = request.form.get('comment') or ''
    line_raw = request.form.get('line_id')
    line_id = None
    try:
        if line_raw not in (None, '', 'all'):
            line_id = int(line_raw)
        visual_feedback_service.add_change_request(
            link.tenant_id, link.resource_id, line_id, comment,
            share_link=link, author_name=name)
        flash('Your change request has been sent. We will get back to you shortly.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return _back(token, line_id)


# ------------------------------------------------------------------ #
#  Quotation actions
# ------------------------------------------------------------------ #
@public_share_bp.route('/<token>/quotation/accept', methods=['POST'])
def quotation_accept(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.QUOTATION:
        abort(404)

    name = (request.form.get('accepted_by_name') or '').strip()
    if not name:
        flash('Please enter your full name to accept the quotation.', 'error')
        return redirect(url_for('public_share.view', token=token))

    q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
    if not q:
        abort(404)
    if q.is_expired:
        flash('This quotation has expired. Please contact us for an updated one.', 'error')
        return redirect(url_for('public_share.view', token=token))

    try:
        quotation_service.accept_quotation(
            tenant_id=link.tenant_id,
            quotation_id=link.resource_id,
            acceptance_method='portal',
            accepted_by_name=name,
        )
        share_link_service.record_response(link, 'ACCEPTED')
        flash('Thank you! Your acceptance has been recorded.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('public_share.view', token=token))


@public_share_bp.route('/<token>/quotation/reject', methods=['POST'])
def quotation_reject(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.QUOTATION:
        abort(404)

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('Please tell us briefly why you are declining.', 'error')
        return redirect(url_for('public_share.view', token=token))

    try:
        quotation_service.mark_lost(
            link.tenant_id, link.resource_id, f'Declined by customer: {reason}'
        )
        share_link_service.record_response(link, 'REJECTED')
        flash('Your response has been recorded. Thank you for letting us know.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('public_share.view', token=token))


@public_share_bp.route('/<token>/quotation/pdf')
def quotation_pdf(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.QUOTATION:
        abort(404)

    q = quotation_service.get_quotation(link.tenant_id, link.resource_id)
    if not q or q.status in (QuotationStatus.DRAFT, QuotationStatus.PENDING_DISCOUNT_APPROVAL):
        abort(404)

    if q.pdf_path:
        full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], q.pdf_path)
        if os.path.exists(full_path):
            return send_file(
                full_path,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'{q.quotation_number}.pdf',
            )

    try:
        tenant = Tenant.query.get(link.tenant_id)
        pdf_bytes = generate_quotation_pdf(quotation=q, project=q.project, tenant=tenant)

        pdf_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pdfs')
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_filename = f'quotation-{q.id}-{q.quotation_number}.pdf'
        with open(os.path.join(pdf_dir, pdf_filename), 'wb') as f:
            f.write(pdf_bytes)
        q.pdf_path = f'pdfs/{pdf_filename}'
        db.session.commit()

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'{q.quotation_number}.pdf',
        )
    except Exception as exc:
        current_app.logger.exception('public quotation_pdf error link=%s: %s', link.id, exc)
        flash('The PDF could not be generated. Please try again shortly.', 'error')
        return redirect(url_for('public_share.view', token=token))


# ------------------------------------------------------------------ #
#  Design approval actions
# ------------------------------------------------------------------ #
@public_share_bp.route('/<token>/design/pdf')
def design_pdf(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.DESIGN_APPROVAL:
        abort(404)

    approval = design_approval_service.get_approval(link.tenant_id, link.resource_id)
    if not approval or approval.status in (
        DesignApprovalStatus.DRAFT, DesignApprovalStatus.SUBMITTED
    ):
        abort(404)

    try:
        tenant = Tenant.query.get(link.tenant_id)
        pdf_bytes = design_render_service.build_design_pdf(
            approval=approval, project=approval.project, tenant=tenant,
        )
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'design-approval-rev{approval.revision_number}.pdf',
        )
    except Exception as exc:
        current_app.logger.exception('public design_pdf error link=%s: %s', link.id, exc)
        flash('The PDF could not be generated. Please try again shortly.', 'error')
        return redirect(url_for('public_share.view', token=token))



@public_share_bp.route('/<token>/design/approve', methods=['POST'])
def design_approve(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.DESIGN_APPROVAL:
        abort(404)

    name = (request.form.get('signoff_name') or '').strip()
    if not name:
        flash('Please enter your full name to approve the design.', 'error')
        return redirect(url_for('public_share.view', token=token))

    notes = (request.form.get('notes') or '').strip()
    signoff = f'Approved online by {name}' + (f' — {notes}' if notes else '')

    try:
        design_approval_service.approve(
            link.tenant_id, link.resource_id, approved_by=None,
            customer_signoff_notes=signoff,
        )
        share_link_service.record_response(link, 'APPROVED')
        flash('Thank you! Your design approval has been recorded.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('public_share.view', token=token))


@public_share_bp.route('/<token>/design/request-changes', methods=['POST'])
def design_request_changes(token):
    link, err = _resolve(token)
    if err:
        return err
    if link.resource_type != ShareLinkType.DESIGN_APPROVAL:
        abort(404)

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('Please describe the changes you would like.', 'error')
        return redirect(url_for('public_share.view', token=token))

    try:
        design_approval_service.request_revision(
            link.tenant_id, link.resource_id, requested_by=None, reason=reason,
        )
        share_link_service.record_response(link, 'CHANGES_REQUESTED')
        flash('Your change request has been sent. We will get back to you shortly.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('public_share.view', token=token))
