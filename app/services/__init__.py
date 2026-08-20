"""Service package initialization and export compatibility patches."""

# Keep existing callers of app.services.engineering_dxf on the corrected
# generator without changing every route/import site.
from . import engineering_dxf as _engineering_dxf
from .engineering_dxf_fixed import generate_engineering_dxf

_engineering_dxf.generate_engineering_dxf = generate_engineering_dxf
