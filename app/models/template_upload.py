from datetime import datetime
from ..extensions import db


class TemplateUpload(db.Model):
    __tablename__ = 'template_uploads'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    response_id = db.Column(db.Integer, db.ForeignKey('template_responses.id'), nullable=False, index=True)

    stored_filename   = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    content_type      = db.Column(db.String(100), nullable=True)
    file_size         = db.Column(db.Integer, nullable=True)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    response = db.relationship('TemplateResponse', backref=db.backref('uploads', lazy='dynamic'))

    def to_dict(self) -> dict:
        return {
            'id':                 self.id,
            'response_id':        self.response_id,
            'stored_filename':    self.stored_filename,
            'original_filename':  self.original_filename,
            'content_type':       self.content_type,
            'file_size':          self.file_size,
            'uploaded_at':        self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

    def __repr__(self):
        return f'<TemplateUpload {self.original_filename} response={self.response_id}>'
