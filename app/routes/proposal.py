import io
import os
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..services.domain import quotation_service
from ..services.domain import proposal_template_store as tpl_store
from ..services.domain.proposal_service import (
    create_proposal,
    get_proposal,
    proposal_full_path,
)

proposal_bp = Blueprint("proposal", __name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard.index"))
        return f(*args, **kwargs)
    return decorated


def _use_llm() -> bool:
    return request.args.get("llm", "1") != "0"


def _template_name():
    return (request.args.get("template") or "").strip() or None


def _load_quotation(quotation_id: int):
    q = quotation_service.get_quotation(current_user.tenant_id, quotation_id)
    if not q:
        abort(404)
    return q


# ------------------------------------------------------------------ #
#  GET /quotations/<id>/proposal.docx
# ------------------------------------------------------------------ #
@proposal_bp.route("/quotations/<int:quotation_id>/proposal.docx")
@login_required
def download_docx(quotation_id):
    q = _load_quotation(quotation_id)
    try:
        result = create_proposal(
            quotation=q,
            project=q.project,
            tenant=current_user.tenant,
            user_id=current_user.id,
            with_pdf=False,
            use_llm=_use_llm(),
            template_filename=_template_name(),
        )
        proposal = result["proposal"]

        return send_file(
            io.BytesIO(result["docx_bytes"]),
            mimetype=DOCX_MIME,
            as_attachment=True,
            download_name=os.path.basename(proposal.docx_path),
        )
    except Exception as exc:
        current_app.logger.exception("proposal docx error quotation=%s: %s", quotation_id, exc)
        flash("Proposal (DOCX) generation failed. Please try again.", "error")
        return redirect(url_for("quotation.detail", quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  GET /quotations/<id>/proposal.pdf
# ------------------------------------------------------------------ #
@proposal_bp.route("/quotations/<int:quotation_id>/proposal.pdf")
@login_required
def download_pdf(quotation_id):
    q = _load_quotation(quotation_id)
    try:
        result = create_proposal(
            quotation=q,
            project=q.project,
            tenant=current_user.tenant,
            user_id=current_user.id,
            with_pdf=True,
            use_llm=_use_llm(),
            template_filename=_template_name(),
        )
        proposal = result["proposal"]

        return send_file(
            io.BytesIO(result["pdf_bytes"]),
            mimetype=PDF_MIME,
            as_attachment=True,
            download_name=os.path.basename(proposal.pdf_path),
        )
    except Exception as exc:
        current_app.logger.exception("proposal pdf error quotation=%s: %s", quotation_id, exc)
        flash("Proposal (PDF) generation failed. Check that LibreOffice is installed.", "error")
        return redirect(url_for("quotation.detail", quotation_id=quotation_id))


# ------------------------------------------------------------------ #
#  GET /quotations/<id>/proposals/<proposal_id>/docx|pdf  (history)
# ------------------------------------------------------------------ #
def _send_saved(quotation_id: int, proposal_id: int, kind: str):
    _load_quotation(quotation_id)
    proposal = get_proposal(current_user.tenant_id, proposal_id)
    if not proposal or proposal.quotation_id != quotation_id:
        abort(404)

    relative = proposal.docx_path if kind == "docx" else proposal.pdf_path
    full = proposal_full_path(relative)
    if not full:
        flash("Saved proposal file was not found on the server.", "error")
        return redirect(url_for("quotation.detail", quotation_id=quotation_id))

    return send_file(
        full,
        mimetype=DOCX_MIME if kind == "docx" else PDF_MIME,
        as_attachment=True,
        download_name=os.path.basename(full),
    )


@proposal_bp.route("/quotations/<int:quotation_id>/proposals/<int:proposal_id>/docx")
@login_required
def history_docx(quotation_id, proposal_id):
    return _send_saved(quotation_id, proposal_id, "docx")


@proposal_bp.route("/quotations/<int:quotation_id>/proposals/<int:proposal_id>/pdf")
@login_required
def history_pdf(quotation_id, proposal_id):
    return _send_saved(quotation_id, proposal_id, "pdf")


# ================================================================== #
#  TEMPLATE MANAGEMENT  (Settings)
# ================================================================== #

# ------------------------------------------------------------------ #
#  GET /settings/proposal-templates
# ------------------------------------------------------------------ #
@proposal_bp.route("/settings/proposal-templates")
@login_required
@admin_required
def templates_index():
    tenant_id = current_user.tenant_id
    return render_template(
        "settings/proposal_templates.html",
        templates=tpl_store.list_templates(tenant_id),
        using_builtin=tpl_store.get_default_name(tenant_id) is None,
    )


# ------------------------------------------------------------------ #
#  POST /settings/proposal-templates/upload
# ------------------------------------------------------------------ #
@proposal_bp.route("/settings/proposal-templates/upload", methods=["POST"])
@login_required
@admin_required
def templates_upload():
    file = request.files.get("template_file")
    if not file or not file.filename:
        flash("Choose a .docx file to upload.", "error")
        return redirect(url_for("proposal.templates_index"))

    try:
        stored = tpl_store.save_template(current_user.tenant_id, file)
        if request.form.get("make_default") == "1":
            tpl_store.set_default(current_user.tenant_id, stored)
        flash(f"Template '{stored}' uploaded.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception as exc:
        current_app.logger.exception("proposal template upload error: %s", exc)
        flash("Template upload failed.", "error")

    return redirect(url_for("proposal.templates_index"))


# ------------------------------------------------------------------ #
#  POST /settings/proposal-templates/default
# ------------------------------------------------------------------ #
@proposal_bp.route("/settings/proposal-templates/default", methods=["POST"])
@login_required
@admin_required
def templates_set_default():
    filename = (request.form.get("filename") or "").strip()
    try:
        tpl_store.set_default(current_user.tenant_id, filename or None)
        flash(
            f"'{filename}' is now the default template." if filename
            else "Built-in template is now the default.",
            "success",
        )
    except FileNotFoundError:
        flash("Template not found.", "error")
    return redirect(url_for("proposal.templates_index"))


# ------------------------------------------------------------------ #
#  POST /settings/proposal-templates/delete
# ------------------------------------------------------------------ #
@proposal_bp.route("/settings/proposal-templates/delete", methods=["POST"])
@login_required
@admin_required
def templates_delete():
    filename = (request.form.get("filename") or "").strip()
    try:
        tpl_store.delete_template(current_user.tenant_id, filename)
        flash(f"Template '{filename}' deleted.", "success")
    except FileNotFoundError:
        flash("Template not found.", "error")
    return redirect(url_for("proposal.templates_index"))


# ------------------------------------------------------------------ #
#  GET /settings/proposal-templates/download/<filename>
#  GET /settings/proposal-templates/download-builtin
# ------------------------------------------------------------------ #
@proposal_bp.route("/settings/proposal-templates/download/<path:filename>")
@login_required
@admin_required
def templates_download(filename):
    full = os.path.join(tpl_store.tenant_dir(current_user.tenant_id), secure_filename(filename))
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, mimetype=DOCX_MIME, as_attachment=True,
                     download_name=secure_filename(filename))


@proposal_bp.route("/settings/proposal-templates/download-builtin")
@login_required
@admin_required
def templates_download_builtin():
    full = tpl_store.builtin_template_path()
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, mimetype=DOCX_MIME, as_attachment=True,
                     download_name=tpl_store.BUILTIN_DEFAULT)
