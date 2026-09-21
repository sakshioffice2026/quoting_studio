from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models.manufacturing_job import JobStatus, ProductionStage, QcResult
from ..services.domain import manufacturing_service

manufacturing_bp = Blueprint('manufacturing', __name__)


# ------------------------------------------------------------------ #
#  GET /manufacturing  — list all jobs for tenant
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing')
@login_required
def index():
    status = request.args.get('status') or None
    jobs = manufacturing_service.list_jobs(current_user.tenant_id, status=status)
    return render_template(
        'manufacturing_jobs.html',
        jobs=jobs,
        status_filter=status,
        JobStatus=JobStatus,
    )


# ------------------------------------------------------------------ #
#  GET /manufacturing/<id>  — detail view
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing/<int:job_id>')
@login_required
def detail(job_id):
    job = manufacturing_service.get_job(current_user.tenant_id, job_id)
    if not job:
        flash('Manufacturing job not found.', 'error')
        return redirect(url_for('manufacturing.index'))
    return render_template(
        'manufacturing_job_detail.html',
        job=job,
        JobStatus=JobStatus,
        ProductionStage=ProductionStage,
        QcResult=QcResult,
    )


# ------------------------------------------------------------------ #
#  POST /orders/<id>/manufacturing/generate
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/orders/<int:order_id>/manufacturing/generate', methods=['POST'])
@login_required
def generate(order_id):
    planned_completion_date = request.form.get('planned_completion_date') or None
    if planned_completion_date:
        planned_completion_date = datetime.strptime(planned_completion_date, '%Y-%m-%d').date()
    try:
        jobs = manufacturing_service.generate_jobs_for_order(
            tenant_id               = current_user.tenant_id,
            order_id                = order_id,
            planned_completion_date = planned_completion_date,
        )
        flash(f'{len(jobs)} manufacturing job(s) queued.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('order.detail', order_id=order_id))


# ------------------------------------------------------------------ #
#  POST /manufacturing/<id>/start
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing/<int:job_id>/start', methods=['POST'])
@login_required
def start(job_id):
    try:
        job = manufacturing_service.start_job(
            current_user.tenant_id, job_id, assigned_to=current_user.id
        )
        flash(f'Job {job.job_number} started.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('manufacturing.detail', job_id=job_id))


# ------------------------------------------------------------------ #
#  POST /manufacturing/<id>/advance
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing/<int:job_id>/advance', methods=['POST'])
@login_required
def advance(job_id):
    material_batch_ref = request.form.get('material_batch_ref') or None
    target_stage       = request.form.get('target_stage') or None
    if target_stage and target_stage not in ProductionStage.ALL:
        flash('Please select a valid stage.', 'error')
        return redirect(url_for('manufacturing.detail', job_id=job_id))
    try:
        job = manufacturing_service.advance_stage(
            current_user.tenant_id, job_id,
            material_batch_ref=material_batch_ref,
            target_stage=target_stage,
        )
        flash(f'Job {job.job_number} moved to {job.stage_label}.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('manufacturing.detail', job_id=job_id))


# ------------------------------------------------------------------ #
#  POST /manufacturing/<id>/qc
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing/<int:job_id>/qc', methods=['POST'])
@login_required
def qc(job_id):
    qc_result = request.form.get('qc_result', '')
    qc_notes  = request.form.get('qc_notes') or None
    if qc_result not in QcResult.ALL:
        flash('A valid QC result is required.', 'error')
        return redirect(url_for('manufacturing.detail', job_id=job_id))
    try:
        job = manufacturing_service.record_qc(
            tenant_id     = current_user.tenant_id,
            job_id        = job_id,
            qc_result     = qc_result,
            qc_checked_by = current_user.id,
            qc_notes      = qc_notes,
        )
        flash(f'QC recorded for {job.job_number}: {qc_result}.', 'success' if qc_result == QcResult.PASS else 'warning')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('manufacturing.detail', job_id=job_id))


# ------------------------------------------------------------------ #
#  POST /manufacturing/<id>/complete
# ------------------------------------------------------------------ #
@manufacturing_bp.route('/manufacturing/<int:job_id>/complete', methods=['POST'])
@login_required
def complete(job_id):
    try:
        job = manufacturing_service.complete_job(current_user.tenant_id, job_id)
        flash(f'Job {job.job_number} completed.', 'success')
    except (ValueError, LookupError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('manufacturing.detail', job_id=job_id))