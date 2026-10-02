"""
Bridge between the Flask app and the standalone `step_generator` package.

The generator needs cadquery (OpenCASCADE) and is heavy, so it is run in a
child process with a timeout. A crash or hang there can never take the web
server down, and cadquery is never imported into the app process.

    data, filename = generate_step(window)
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from flask import current_app

logger = logging.getLogger(__name__)

STEP_TIMEOUT_SECONDS = 240


class StepGeneratorError(Exception):
    """Generation failed (build, validation, timeout or missing package)."""


class StepUnsupportedError(StepGeneratorError):
    """This unit type is not covered by the step generator yet."""


def _project_root() -> Path:
    # current_app.root_path is <project>/app
    return Path(current_app.root_path).parent


def _design(window) -> dict:
    raw = getattr(window, "design_json", None)
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _positive(value, fallback: float) -> float:
    try:
        number = float(value)
        if number > 0:
            return number
    except (TypeError, ValueError):
        pass
    return float(fallback)


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_")[:30] or "unit"


def resolve_kind(window) -> tuple[str, float, float]:
    """Returns (kind, width_mm, height_mm) where kind is 'window' or 'door'."""
    design = _design(window)
    width = _positive(design.get("width"), window.width_mm or 1200)
    height = _positive(design.get("height"), window.height_mm or 1400)

    unit_type = str(design.get("unitType") or "window").lower()
    if unit_type == "door":
        dtype = str((design.get("door") or {}).get("dtype") or "single").lower()
        if dtype != "double":
            raise StepUnsupportedError(
                "The STEP generator currently supports windows and double doors only."
            )
        return "door", width, height

    return "window", width, height


def _last_error(proc: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith("FAILED:"):
            return line[len("FAILED:"):].strip() or "STEP generation failed"
    if lines:
        return lines[-1]
    return "STEP generation failed"


def generate_step(window, timeout: int = STEP_TIMEOUT_SECONDS) -> tuple[bytes, str]:
    """Runs the generator for one window/door. Returns (step_bytes, filename)."""
    kind, width, height = resolve_kind(window)
    module = "step_generator.generate_door" if kind == "door" else "step_generator.generate_window"

    root = _project_root()
    if not (root / "step_generator").is_dir():
        raise StepGeneratorError("step_generator folder not found next to the app.")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, f"{kind}.step")
        cmd = [
            sys.executable, "-m", module,
            "--width", f"{width:g}",
            "--height", f"{height:g}",
            "--out", out_path,
        ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise StepGeneratorError(f"STEP generation timed out after {timeout}s") from exc

        if proc.returncode != 0 or not os.path.isfile(out_path):
            message = _last_error(proc)
            logger.error(
                "step_generator failed window=%s kind=%s rc=%s: %s",
                getattr(window, "id", None), kind, proc.returncode, message,
            )
            raise StepGeneratorError(message)

        with open(out_path, "rb") as fh:
            data = fh.read()

    if not data:
        raise StepGeneratorError("STEP generation produced an empty file.")

    filename = f"QS-{window.id}-{_safe(window.label)}-{kind}.step"
    return data, filename
