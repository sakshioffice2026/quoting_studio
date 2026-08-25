"""
app/services/techdraw_export.py -- 2D drawing export via headless FreeCAD.

Single-session pipeline: app/services/model3d_freecad.py builds the member
solids AND projects/writes the SVG inside ONE freecadcmd process (see
generate_techdraw_freecad / _build_drawing_script there). This module is now
a thin wrapper kept for backward-compatible imports -- it no longer builds a
STEP file with cadquery and reloads it in a second FreeCAD process.
"""
from __future__ import annotations
import logging

from .model3d_freecad import generate_techdraw_freecad

logger = logging.getLogger(__name__)


def generate_techdraw(window, panes, tenant_id=None, fmt='svg') -> bytes:
    fmt = fmt.lower()
    if fmt not in ('svg', 'pdf'):
        raise ValueError("fmt must be 'svg' or 'pdf'")
    return generate_techdraw_freecad(window, panes, tenant_id=tenant_id, fmt=fmt)