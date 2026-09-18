from flask import Blueprint

api_v1_bp = Blueprint('api_v1', __name__)

from .windows import windows_bp          # noqa: E402
from .cad import cad_bp                  # noqa: E402
from .visualisation import vis_bp        # noqa: E402
from .leads_api import leads_api_bp
from .preliminary_selection_api import presel_api_bp

api_v1_bp.register_blueprint(windows_bp)
api_v1_bp.register_blueprint(cad_bp)
api_v1_bp.register_blueprint(vis_bp)
api_v1_bp.register_blueprint(leads_api_bp)
api_v1_bp.register_blueprint(presel_api_bp)
