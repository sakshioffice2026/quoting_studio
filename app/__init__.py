import os
from flask import Flask, jsonify, render_template
from .extensions import db, login_manager, migrate, csrf
from config import config


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # ensure upload sub-directories exist
    for sub in ('photos', 'renders', 'pdfs', 'logos'):
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], sub), exist_ok=True)

    # initialise extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # initialise logging (must come before blueprints so handlers are ready)
    from .logging_config import setup_logging
    setup_logging(app)

    # import models so Alembic can detect them
    with app.app_context():
        from .models import (  # noqa: F401
            Tenant, User, Project, Window, Pane,
            Visualisation, Quote, PricingRule,
            OpenerPricingRule, GlazingPricingRule,
            ExceptionLog,
            CadProfile,
            ProductSeries, WindowStyle,
        )

    # register blueprints
    from .routes.auth import auth_bp
    from .routes.customers import customers_bp
    from .routes.reports import reports_bp
    from .routes.model3d_route import model3d_bp
    from .routes.settings import settings_bp
    from .routes.dashboard import dashboard_bp
    from .routes.projects import projects_bp
    from .routes.editor import editor_bp
    from .routes.visualiser import visualiser_bp
    from .routes.quote import quote_bp
    from .api.v1 import api_v1_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(model3d_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(visualiser_bp)
    app.register_blueprint(quote_bp)
    app.register_blueprint(api_v1_bp, url_prefix='/api/v1')

    # ---- serve uploaded files -------------------------------------
    import os as _os
    from flask import send_from_directory

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # ---- global error handlers ------------------------------------
    _register_error_handlers(app)

    return app


def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(400)
    def bad_request(e):
        app.logger.warning('400 Bad Request: %s — %s', e, _req_info())
        if _is_api_request():
            return jsonify(error='Bad request', detail=str(e)), 400
        return render_template('errors/400.html'), 400

    @app.errorhandler(403)
    def forbidden(e):
        app.logger.warning('403 Forbidden: %s — %s', e, _req_info())
        if _is_api_request():
            return jsonify(error='Forbidden'), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        app.logger.info('404 Not Found — %s', _req_info())
        if _is_api_request():
            return jsonify(error='Not found'), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        # DB session may be broken — roll back before doing anything else
        try:
            from .extensions import db as _db
            _db.session.rollback()
        except Exception:
            pass
        app.logger.exception('500 Internal Server Error — %s: %s', _req_info(), e)
        if _is_api_request():
            return jsonify(error='Internal server error'), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        try:
            from .extensions import db as _db
            _db.session.rollback()
        except Exception:
            pass
        app.logger.exception('Unhandled exception — %s: %s', _req_info(), e)
        if _is_api_request():
            return jsonify(error='Unexpected server error'), 500
        return render_template('errors/500.html'), 500


def _req_info() -> str:
    """Safe one-liner summary of the current request for log messages."""
    try:
        from flask import request
        return f'{request.method} {request.path}'
    except Exception:
        return '(no request context)'


def _is_api_request() -> bool:
    """True when the request path starts with /api/."""
    try:
        from flask import request
        return request.path.startswith('/api/')
    except Exception:
        return False