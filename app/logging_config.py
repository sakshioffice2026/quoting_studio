import logging
import traceback
import os
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, unquote


# ================================================================
#  DB LOG HANDLER
#  Uses raw pymysql — no SQLAlchemy ORM involved — so it never
#  causes circular imports, recursive logging, or session conflicts.
# ================================================================
class DBLogHandler(logging.Handler):
    """
    Writes WARNING+ records to the exception_logs MySQL table.
    Uses a fresh pymysql connection per record (kept short-lived).
    Silently swallows any failure so logging never breaks the app.
    """

    def __init__(self, db_url: str):
        super().__init__(level=logging.WARNING)
        self._conn_kwargs = self._parse_db_url(db_url)

    # ----------------------------------------------------------------
    @staticmethod
    def _parse_db_url(url: str) -> dict:
        """
        Parse  mysql+pymysql://user:pass@host:port/dbname
        into a pymysql.connect() kwargs dict.
        """
        # strip dialect prefix
        raw = url.replace('mysql+pymysql://', 'mysql://')
        p   = urlparse(raw)
        return dict(
            host    = p.hostname or 'localhost',
            port    = p.port    or 3306,
            user    = unquote(p.username or 'root'),
            password= unquote(p.password or ''),
            database= p.path.lstrip('/'),
            charset = 'utf8mb4',
            connect_timeout = 3,
        )

    # ----------------------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        try:
            import pymysql

            # ---- request / user context (best-effort) ---------------
            url = method = ip = None
            user_id = tenant_id = None
            try:
                from flask import request, has_request_context
                if has_request_context():
                    url    = (request.url or '')[:500]
                    method = request.method
                    ip     = request.remote_addr
            except Exception:
                pass

            try:
                from flask_login import current_user
                if current_user and current_user.is_authenticated:
                    user_id   = current_user.id
                    tenant_id = current_user.tenant_id
            except Exception:
                pass

            # ---- exception details ----------------------------------
            exc_type = exc_msg = tb_text = None
            if record.exc_info and record.exc_info[0]:
                exc_type = record.exc_info[0].__name__
                exc_msg  = str(record.exc_info[1])
                tb_text  = ''.join(traceback.format_exception(*record.exc_info))

            message = self.format(record)

            # ---- write to DB ----------------------------------------
            conn = pymysql.connect(**self._conn_kwargs)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO exception_logs
                            (level, module, func_name, line_no, message,
                             exc_type, exc_message, traceback,
                             url, method, user_id, tenant_id, ip_address)
                        VALUES
                            (%s, %s, %s, %s, %s,
                             %s, %s, %s,
                             %s, %s, %s, %s, %s)
                        """,
                        (
                            record.levelname,
                            record.module,
                            record.funcName,
                            record.lineno,
                            message[:4000],
                            exc_type,
                            exc_msg,
                            tb_text,
                            url, method, user_id, tenant_id, ip,
                        )
                    )
                conn.commit()
            finally:
                conn.close()

        except Exception:
            # NEVER let the log handler crash the application
            self.handleError(record)


# ================================================================
#  MAIN SETUP FUNCTION
# ================================================================
def setup_logging(app) -> None:
    """
    Attach three handlers to the Flask app logger:
      1. Rotating file  — INFO+   → logs/quoting_studio.log
      2. Console        — DEBUG in dev, WARNING in prod
      3. DB handler     — WARNING+ → exception_logs table
    """
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s %(module)s:%(lineno)d — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # ---- 1. rotating file ------------------------------------------
    fh = RotatingFileHandler(
        os.path.join(log_dir, 'quoting_studio.log'),
        maxBytes  = 5 * 1024 * 1024,
        backupCount = 5,
        encoding  = 'utf-8',
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)

    # ---- 2. console ------------------------------------------------
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.DEBUG if app.debug else logging.WARNING)

    # ---- 3. DB handler ---------------------------------------------
    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    dh = DBLogHandler(db_url)
    dh.setFormatter(fmt)

    app.logger.setLevel(logging.DEBUG)
    app.logger.addHandler(fh)
    app.logger.addHandler(ch)
    app.logger.addHandler(dh)

    # keep SQLAlchemy quiet (flip to DEBUG only when debugging queries)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    app.logger.info('Quoting Studio — logging initialised (debug=%s)', app.debug)
