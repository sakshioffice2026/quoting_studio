import os
import uuid
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models.installation import InstallationStatus, TestResult
from ..services.domain import installation_service

installation_bp = Blueprint('installation', __name__)

_ALLOWED_HANDOVER_EXT = {'.jpg', '.jpeg', '.png', '.pdf'}


@installation_bp.app_template_global('installation_summary')
def _installation_summary(order_id):
    """Order-level installation progress for use in any template."""
    return installation_service.order_summary(current_user.tenant_id, order_id)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _save_handover(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in _ALLOWED_HANDOVER_EXT:
        raise ValueError('Signed handover certificate must be a JPG, PNG or PDF file.')
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'handover')
    os.makedirs(folder, exist_ok=True)
    name = f'{uuid.uuid4().hex}{ext}'
    file_storage.save(os.path.join(folder, name))
    return f'handover/{name}'


# ------------------------------------------------------------------ #
#  GET /installations
# ------------------------------------------------------------------ #
@installation_bp.route('/installations')
@login_required
def index():
    status = request.args.get('status') or None
    installations = installation_service.list_installations(current_user.tenant_id, status=status)
    ready_orders  = installation_service.orders_ready_for_installation(current_user.tenant_id)
    return render_template(
        'installations.html',
        installations=installations,
        ready_orders=ready_orders,
        status_filter=status,
        InstallationStatus=InstallationStatus,
    )


# ------------------------------------------------------------------ #
#  GET /installations/<id>
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>')
@login_required
def detail(installation_id):
    installation = installation_service.get_installation(current_user.tenant_id, installation_id)
    if not installation:
        flash('Installation not found.', 'error')
        return redirect(url_for('installation.index'))
    return render_template(
        'installation_detail.html',
        installation=installation,
        payments=installation_service.on_installation_payments(
            current_user.tenant_id, installation.order_id),
        InstallationStatus=InstallationStatus,
        TestResult=TestResult,
    )


# ------------------------------------------------------------------ #
#  GET /installations/<id>/certificate  — printable handover certificate
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/certificate')
@login_required
def certificate(installation_id):
    installation = installation_service.get_installation(current_user.tenant_id, installation_id)
    if not installation:
        flash('Installation not found.', 'error')
        return redirect(url_for('installation.index'))
    return render_template('installation_certificate.html', installation=installation)


# ------------------------------------------------------------------ #
#  POST /orders/<id>/installations/create   (schedule)
# ------------------------------------------------------------------ #
@installation_bp.route('/orders/<int:order_id>/installations/create', methods=['POST'])
@login_required
def create(order_id):
    opening_ids = [int(x) for x in request.form.getlist('opening_ids') if x.isdigit()]
    try:
        installation = installation_service.create_installation(
            tenant_id            = current_user.tenant_id,
            order_id             = order_id,
            created_by           = current_user.id,
            opening_ids          = opening_ids or None,
            scheduled_date       = _parse_date(request.form.get('scheduled_date')),
            team_lead_name       = (request.form.get('team_lead_name') or '').strip() or None,
            installation_address = request.form.get('installation_address') or None,
            site_contact_name    = request.form.get('site_contact_name') or None,
            site_contact_phone   = request.form.get('site_contact_phone') or None,
        )
        flash(f'Installation {installation.install_number} scheduled.', 'success')
        return redirect(url_for('installation.detail', installation_id=installation.id))
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('installation.index'))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/reschedule
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/reschedule', methods=['POST'])
@login_required
def reschedule(installation_id):
    try:
        installation = installation_service.reschedule_installation(
            tenant_id       = current_user.tenant_id,
            installation_id = installation_id,
            scheduled_date  = _parse_date(request.form.get('scheduled_date')),
            team_lead_name  = (request.form.get('team_lead_name') or '').strip() or None,
        )
        flash(f'Installation {installation.install_number} rescheduled.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/start
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/start', methods=['POST'])
@login_required
def start(installation_id):
    try:
        installation = installation_service.start_installation(
            tenant_id       = current_user.tenant_id,
            installation_id = installation_id,
            team_lead_name  = (request.form.get('team_lead_name') or '').strip() or None,
        )
        flash(f'Installation {installation.install_number} started.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/items/<item_id>/record
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/items/<int:item_id>/record', methods=['POST'])
@login_required
def record_item(installation_id, item_id):
    try:
        installation = installation_service.record_opening(
            tenant_id         = current_user.tenant_id,
            installation_id   = installation_id,
            item_id           = item_id,
            installed_by      = (request.form.get('installed_by') or '').strip(),
            result            = request.form.get('functional_test_result') or '',
            fitted            = request.form.get('fitted') == 'on',
            hardware_adjusted = request.form.get('hardware_adjusted') == 'on',
            joints_sealed     = request.form.get('joints_sealed') == 'on',
            site_cleaned      = request.form.get('site_cleaned') == 'on',
            snag_list         = (request.form.get('snag_list') or '').strip() or None,
        )
        if installation.status == InstallationStatus.SNAG:
            flash('Opening recorded — installation has open snags.', 'warning')
        else:
            flash('Opening recorded.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/items/<item_id>/resolve
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/items/<int:item_id>/resolve', methods=['POST'])
@login_required
def resolve_item(installation_id, item_id):
    try:
        installation_service.resolve_snag(
            current_user.tenant_id, installation_id, item_id,
            resolution_notes=request.form.get('resolution_notes') or None,
        )
        flash('Snag marked as resolved — re-test the opening.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/resolve-all
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/resolve-all', methods=['POST'])
@login_required
def resolve_all(installation_id):
    try:
        installation = installation_service.resolve_all_snags(
            current_user.tenant_id, installation_id,
            resolution_notes=request.form.get('resolution_notes') or None,
        )
        flash(f'All snags resolved on {installation.install_number} — re-test the openings.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))


# ------------------------------------------------------------------ #
#  POST /installations/<id>/signoff
# ------------------------------------------------------------------ #
@installation_bp.route('/installations/<int:installation_id>/signoff', methods=['POST'])
@login_required
def signoff(installation_id):
    try:
        file_path    = _save_handover(request.files.get('handover_file'))
        installation = installation_service.sign_off(
            tenant_id          = current_user.tenant_id,
            installation_id    = installation_id,
            signed_by          = (request.form.get('signed_by') or '').strip(),
            handover_notes     = request.form.get('handover_notes') or None,
            handover_file_path = file_path,
        )
        flash(f'Installation {installation.install_number} signed off and handed over.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('installation.detail', installation_id=installation_id))
