from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile

from flask import current_app

from ...extensions import db
from ...models.proposal import Proposal
from .proposal_context_service import build_proposal_context
from .proposal_copy_service import generate_proposal_copy
from .proposal_docx_service import fill_docx_template
from .proposal_template_store import resolve_template_path

logger = logging.getLogger(__name__)

OUTPUT_DIR = "proposals"
PDF_TIMEOUT_SECONDS = 90

_WINDOWS_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


# ------------------------------------------------------------------ #
#  Paths
# ------------------------------------------------------------------ #

def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_") or "proposal"


def proposal_filename(quotation, extension: str, revision_no: int | None = None) -> str:
    base = f"proposal-{_safe_name(quotation.quotation_number)}-v{quotation.quotation_version or 1}"
    if revision_no:
        base += f"-r{revision_no}"
    return f"{base}.{extension}"


def save_proposal_file(tenant_id: int, filename: str, data: bytes) -> str:
    """Saves under UPLOAD_FOLDER/proposals/<tenant_id>/ and returns the relative path."""
    out_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], OUTPUT_DIR, str(tenant_id))
    os.makedirs(out_dir, exist_ok=True)
    full_path = os.path.join(out_dir, filename)
    with open(full_path, "wb") as fh:
        fh.write(data)
    return f"{OUTPUT_DIR}/{tenant_id}/{filename}"


# ------------------------------------------------------------------ #
#  DOCX
# ------------------------------------------------------------------ #

def generate_proposal_docx(
    quotation,
    project,
    tenant,
    use_llm: bool = True,
    template_filename: str | None = None,
    currency_symbol: str = "$",
) -> dict:
    """
    Returns {
        'bytes': bytes,
        'filename': str,
        'copy_source': 'llm' | 'fallback',
        'template': str
    }
    """
    context = build_proposal_context(quotation, project, tenant, currency_symbol)
    copy_data = generate_proposal_copy(context["llm_input"], use_llm=use_llm)
    template_path = resolve_template_path(quotation.tenant_id, template_filename)

    docx_bytes = fill_docx_template(template_path, context, copy_data)

    return {
        "bytes": docx_bytes,
        "filename": proposal_filename(quotation, "docx"),
        "copy_source": copy_data.get("source", "fallback"),
        "template": os.path.basename(template_path),
    }


# ------------------------------------------------------------------ #
#  PDF (DOCX -> PDF via LibreOffice)
# ------------------------------------------------------------------ #

def _find_soffice() -> str | None:
    env_path = os.environ.get("SOFFICE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found

    for path in _WINDOWS_SOFFICE_PATHS:
        if os.path.isfile(path):
            return path
    return None


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            "LibreOffice not found. Install LibreOffice or set SOFFICE_PATH in .env"
        )

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "proposal.docx")
        with open(src, "wb") as fh:
            fh.write(docx_bytes)

        profile_dir = os.path.join(tmp, "lo_profile")
        profile_uri = "file:///" + profile_dir.replace("\\", "/").lstrip("/")

        cmd = [
            soffice,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--norestore",
            "--convert-to", "pdf",
            "--outdir", tmp,
            src,
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=PDF_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("PDF conversion timed out") from exc
        except subprocess.CalledProcessError as exc:
            logger.error("soffice failed: %s", exc.stderr.decode(errors="ignore"))
            raise RuntimeError("PDF conversion failed") from exc

        pdf_path = os.path.join(tmp, "proposal.pdf")
        if not os.path.isfile(pdf_path):
            raise RuntimeError("PDF conversion produced no output")

        with open(pdf_path, "rb") as fh:
            return fh.read()


def generate_proposal_pdf(
    quotation,
    project,
    tenant,
    use_llm: bool = True,
    template_filename: str | None = None,
    currency_symbol: str = "$",
) -> dict:
    docx_result = generate_proposal_docx(
        quotation, project, tenant,
        use_llm=use_llm,
        template_filename=template_filename,
        currency_symbol=currency_symbol,
    )
    pdf_bytes = convert_docx_to_pdf(docx_result["bytes"])

    return {
        "bytes": pdf_bytes,
        "filename": proposal_filename(quotation, "pdf"),
        "copy_source": docx_result["copy_source"],
        "template": docx_result["template"],
        "docx_bytes": docx_result["bytes"],
        "docx_filename": docx_result["filename"],
    }


# ------------------------------------------------------------------ #
#  Records (history)
# ------------------------------------------------------------------ #

def list_proposals(tenant_id: int, quotation_id: int) -> list[Proposal]:
    return (Proposal.query
            .filter_by(tenant_id=tenant_id, quotation_id=quotation_id)
            .order_by(Proposal.revision_no.desc())
            .all())


def get_proposal(tenant_id: int, proposal_id: int) -> Proposal | None:
    return Proposal.query.filter_by(id=proposal_id, tenant_id=tenant_id).first()


def proposal_full_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    full = os.path.normpath(os.path.join(current_app.config["UPLOAD_FOLDER"], relative_path))
    root = os.path.normpath(current_app.config["UPLOAD_FOLDER"])
    if not full.startswith(root) or not os.path.isfile(full):
        return None
    return full


def create_proposal(
    quotation,
    project,
    tenant,
    user_id: int | None,
    with_pdf: bool = False,
    use_llm: bool = True,
    template_filename: str | None = None,
    currency_symbol: str = "$",
) -> dict:
    """
    Generates a new proposal revision, saves the files and stores a Proposal row.
    Returns {'proposal': Proposal, 'docx_bytes': bytes, 'pdf_bytes': bytes | None}
    """
    revision_no = Proposal.next_revision(quotation.id)

    docx_result = generate_proposal_docx(
        quotation, project, tenant,
        use_llm=use_llm,
        template_filename=template_filename,
        currency_symbol=currency_symbol,
    )
    docx_name = proposal_filename(quotation, "docx", revision_no)
    docx_path = save_proposal_file(quotation.tenant_id, docx_name, docx_result["bytes"])

    pdf_bytes = None
    pdf_path = None
    if with_pdf:
        pdf_bytes = convert_docx_to_pdf(docx_result["bytes"])
        pdf_name = proposal_filename(quotation, "pdf", revision_no)
        pdf_path = save_proposal_file(quotation.tenant_id, pdf_name, pdf_bytes)

    proposal = Proposal(
        tenant_id=quotation.tenant_id,
        quotation_id=quotation.id,
        revision_no=revision_no,
        quotation_version=quotation.quotation_version,
        docx_path=docx_path,
        pdf_path=pdf_path,
        template_name=docx_result["template"],
        copy_source=docx_result["copy_source"],
        grand_total=quotation.grand_total,
        created_by=user_id,
    )
    db.session.add(proposal)
    db.session.commit()

    return {"proposal": proposal, "docx_bytes": docx_result["bytes"], "pdf_bytes": pdf_bytes}
