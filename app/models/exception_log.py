from datetime import datetime
from ..extensions import db


class ExceptionLog(db.Model):
    """
    Stores WARNING / ERROR / CRITICAL log records in the database.
    No FK constraints on user_id / tenant_id — logs must survive
    even if the related rows are later deleted.
    """
    __tablename__ = 'exception_logs'

    id          = db.Column(db.Integer, primary_key=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    level       = db.Column(db.String(10),  nullable=False, index=True)   # WARNING / ERROR / CRITICAL
    module      = db.Column(db.String(100), nullable=True)
    func_name   = db.Column(db.String(100), nullable=True)
    line_no     = db.Column(db.Integer,     nullable=True)
    message     = db.Column(db.Text,        nullable=False)
    exc_type    = db.Column(db.String(200), nullable=True)   # e.g. OperationalError
    exc_message = db.Column(db.Text,        nullable=True)
    traceback   = db.Column(db.Text,        nullable=True)
    url         = db.Column(db.String(500), nullable=True)
    method      = db.Column(db.String(10),  nullable=True)
    user_id     = db.Column(db.Integer,     nullable=True,   index=True)
    tenant_id   = db.Column(db.Integer,     nullable=True,   index=True)
    ip_address  = db.Column(db.String(45),  nullable=True)

    def __repr__(self):
        return f'<ExceptionLog {self.level} {self.module}:{self.line_no}>'
