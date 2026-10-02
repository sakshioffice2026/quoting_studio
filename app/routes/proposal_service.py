from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile

from flask import current_app

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


def proposal_filename(quotation, extension: str) -> str:
    base = f"proposal-{_safe_name(quotation.quotation_number)}-v{quotation.quotation_version or 1}"
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
