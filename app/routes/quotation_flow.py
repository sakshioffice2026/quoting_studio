from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify)
from flask_login import login_required, current_user

from ..models.quotation import QuotationStatus
from ..services.domain import quotation_flow_service as flow
from ..services.domain import gallery_admin_service as gadmin

quotation_flow_bp = Blueprint(
    'quotation_flow', __name__, url_prefix='/quotations/flow'
)


def _draft_or_redirect(quotation_id: int):
    q = flow.get_draft(current_user.tenant_id, quotation_id)
    if not q:
        flash('Draft quotation not found or no longer editable.', 'error')
        return None
    return q


# ------------------------------------------------------------------ #
#  Step 2 — Select Customer modal (data endpoint)
#  GET /quotations/flow/customers?q=
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/customers')
@login_required
def customers():
    term = (request.args.get('q') or '').strip() or None
    rows = flow.search_customers(current_user.tenant_id, term)
    return jsonify([c.to_dict() for c in rows])


# ------------------------------------------------------------------ #
#  Step 2 → 3 — create draft and open builder
#  POST /quotations/flow/start
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/start', methods=['POST'])
@login_required
def start():
    mode = request.form.get('mode', 'existing')
    try:
        if mode == 'walk_in':
            q = flow.create_draft(current_user.tenant_id, current_user.id, customer_id=None)
        elif mode == 'new':
            q = flow.create_customer_and_draft(
                current_user.tenant_id,
                current_user.id,
                name=request.form.get('name', ''),
                phone=(request.form.get('phone') or None),
                email=(request.form.get('email') or None),
                city=(request.form.get('city') or None),
                address=(request.form.get('address') or None),
            )
        else:
            customer_id = request.form.get('customer_id', type=int)
            if not customer_id:
                flash('Please select a customer.', 'error')
                return redirect(url_for('quotation.index'))
            q = flow.create_draft(current_user.tenant_id, current_user.id, customer_id=customer_id)
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('quotation.index'))

    return redirect(url_for('quotation_flow.builder', quotation_id=q.id))


# ------------------------------------------------------------------ #
#  Step 3 — Quotation Builder
#  GET /quotations/flow/<id>/builder
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/builder')
@login_required
def builder(quotation_id):
    q = _draft_or_redirect(quotation_id)
    if not q:
        return redirect(url_for('quotation.index'))
    return render_template(
        'quotation_flow/builder.html',
        quotation=q,
        walk_in=flow.is_walk_in(q),
        can_proceed=bool(q.line_items),
    )


# ------------------------------------------------------------------ #
#  Step 3 → 4 — Pick from Gallery
#  GET /quotations/flow/<id>/gallery
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/gallery')
@login_required
def gallery(quotation_id):
    q = _draft_or_redirect(quotation_id)
    if not q:
        return redirect(url_for('quotation.index'))
    return render_template(
        'quotation_flow/gallery.html',
        quotation=q,
        gallery=flow.list_gallery(current_user.tenant_id),
    )


# ------------------------------------------------------------------ #
#  Step 4 — Review Product (gallery selection)
#  GET /quotations/flow/<id>/review?style_id=
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/review')
@login_required
def review(quotation_id):
    q = _draft_or_redirect(quotation_id)
    if not q:
        return redirect(url_for('quotation.index'))

    style_id = request.args.get('style_id', type=int)
    found = flow.get_style(current_user.tenant_id, style_id) if style_id else None
    if not found:
        flash('Please pick a product from the gallery.', 'error')
        return redirect(url_for('quotation_flow.gallery', quotation_id=quotation_id))

    style, series = found
    return render_template(
        'quotation_flow/review.html',
        quotation=q,
        style=style,
        series=series,
        source='gallery',
    )


# ------------------------------------------------------------------ #
#  Step 4 (alternative) — Configurator entry
#  GET /quotations/flow/<id>/configurator
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/configurator')
@login_required
def configurator(quotation_id):
    q = _draft_or_redirect(quotation_id)
    if not q:
        return redirect(url_for('quotation.index'))
    return render_template(
        'quotation_flow/review.html',
        quotation=q,
        style=None,
        series=None,
        source='configurator',
    )


# ------------------------------------------------------------------ #
#  Step 4 → 3 — add product to quotation
#  POST /quotations/flow/<id>/items
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/items', methods=['POST'])
@login_required
def add_item(quotation_id):
    try:
        flow.add_line_item(
            tenant_id=current_user.tenant_id,
            quotation_id=quotation_id,
            style_id=request.form.get('style_id', type=int),
            label=request.form.get('label', ''),
            width_mm=request.form.get('width_mm', type=int, default=0),
            height_mm=request.form.get('height_mm', type=int, default=0),
            qty=request.form.get('qty', type=int, default=1),
            rate_per_sqft=request.form.get('rate_per_sqft', type=float, default=0.0),
            source=request.form.get('source', 'gallery'),
            notes=(request.form.get('notes') or None),
            design_json=(request.form.get('design_json') or None),
        )
        flash('Product added to quotation.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation_flow.builder', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  POST /quotations/flow/<id>/items/<line_id>/delete
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/items/<int:line_id>/delete', methods=['POST'])
@login_required
def delete_item(quotation_id, line_id):
    try:
        flow.remove_line_item(current_user.tenant_id, quotation_id, line_id)
        flash('Item removed.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('quotation_flow.builder', quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  Step 3 → 5 — Proceed to Quotation
#  POST /quotations/flow/<id>/proceed
# ------------------------------------------------------------------ #
@quotation_flow_bp.route('/<int:quotation_id>/proceed', methods=['POST'])
@login_required
def proceed(quotation_id):
    try:
        q = flow.proceed_to_quotation(current_user.tenant_id, quotation_id)
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('quotation_flow.builder', quotation_id=quotation_id))

    flash(f'Quotation {q.quotation_number} saved as {QuotationStatus.LABELS[q.status]}.', 'success')
    return redirect(url_for('quotation.detail', quotation_id=q.id))


# ================================================================== #
#  Gallery management — add / edit / delete products, upload image & PDF
# ================================================================== #

def _back_to_gallery(quotation_id: int):
    return redirect(url_for('quotation_flow.gallery', quotation_id=quotation_id))


def _guard(quotation_id: int) -> bool:
    return flow.get_draft(current_user.tenant_id, quotation_id) is not None


def _run(quotation_id: int, action, success: str):
    if not _guard(quotation_id):
        flash('Draft quotation not found or no longer editable.', 'error')
        return redirect(url_for('quotation.index'))
    try:
        action()
        flash(success, 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return _back_to_gallery(quotation_id)


# ---- Series -------------------------------------------------------- #

@quotation_flow_bp.route('/<int:quotation_id>/gallery/series', methods=['POST'])
@login_required
def series_create(quotation_id):
    return _run(
        quotation_id,
        lambda: gadmin.create_series(
            current_user.tenant_id,
            name=request.form.get('name', ''),
            material=request.form.get('material'),
            description=request.form.get('description'),
            image_file=request.files.get('image'),
            pdf_file=request.files.get('pdf'),
        ),
        'Series added.',
    )


@quotation_flow_bp.route('/<int:quotation_id>/gallery/series/<int:series_id>/update', methods=['POST'])
@login_required
def series_update(quotation_id, series_id):
    return _run(
        quotation_id,
        lambda: gadmin.update_series(
            current_user.tenant_id,
            series_id,
            name=request.form.get('name', ''),
            material=request.form.get('material'),
            description=request.form.get('description'),
            image_file=request.files.get('image'),
            pdf_file=request.files.get('pdf'),
            remove_pdf=request.form.get('remove_pdf') == '1',
        ),
        'Series updated.',
    )


@quotation_flow_bp.route('/<int:quotation_id>/gallery/series/<int:series_id>/delete', methods=['POST'])
@login_required
def series_delete(quotation_id, series_id):
    return _run(
        quotation_id,
        lambda: gadmin.delete_series(current_user.tenant_id, series_id),
        'Series deleted.',
    )


# ---- Styles (products) -------------------------------------------- #

@quotation_flow_bp.route('/<int:quotation_id>/gallery/styles', methods=['POST'])
@login_required
def style_create(quotation_id):
    return _run(
        quotation_id,
        lambda: gadmin.create_style(
            current_user.tenant_id,
            series_id=request.form.get('series_id', type=int, default=0),
            name=request.form.get('name', ''),
            panels=request.form.get('panels', type=int, default=1),
            image_file=request.files.get('image'),
            pdf_file=request.files.get('pdf'),
        ),
        'Product added.',
    )


@quotation_flow_bp.route('/<int:quotation_id>/gallery/styles/<int:style_id>/update', methods=['POST'])
@login_required
def style_update(quotation_id, style_id):
    return _run(
        quotation_id,
        lambda: gadmin.update_style(
            current_user.tenant_id,
            style_id,
            name=request.form.get('name', ''),
            panels=request.form.get('panels', type=int, default=1),
            image_file=request.files.get('image'),
            pdf_file=request.files.get('pdf'),
            remove_pdf=request.form.get('remove_pdf') == '1',
            remove_image=request.form.get('remove_image') == '1',
        ),
        'Product updated.',
    )


@quotation_flow_bp.route('/<int:quotation_id>/gallery/styles/<int:style_id>/delete', methods=['POST'])
@login_required
def style_delete(quotation_id, style_id):
    return _run(
        quotation_id,
        lambda: gadmin.delete_style(current_user.tenant_id, style_id),
        'Product deleted.',
    )
