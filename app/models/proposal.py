from datetime import datetime

from ..extensions import db


class Proposal(db.Model):
    """
    One row per generated proposal document for a quotation.
    A new row (revision_no + 1) is created each time a proposal is generated.
    """
    __tablename__ = 'proposals'

    id             = db.Column(db.Integer, primary_key=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenants.id'),    nullable=False, index=True)
    quotation_id   = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False, index=True)

    revision_no    = db.Column(db.Integer, nullable=False, default=1)
    quotation_version = db.Column(db.Integer, nullable=True)

    docx_path      = db.Column(db.String(500), nullable=True)
    pdf_path       = db.Column(db.String(500), nullable=True)

    template_name  = db.Column(db.String(255), nullable=True)
    copy_source    = db.Column(db.String(20),  nullable=True)   # llm / fallback
    grand_total    = db.Column(db.Numeric(12, 2), nullable=True)

    created_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    quotation = db.relationship(
        'Quotation',
        backref=db.backref('proposals', lazy='dynamic', cascade='all, delete-orphan'),
    )

    @staticmethod
    def next_revision(quotation_id: int) -> int:
        last = (Proposal.query
                .filter_by(quotation_id=quotation_id)
                .order_by(Proposal.revision_no.desc())
                .first())
        return (last.revision_no + 1) if last else 1

    def to_dict(self) -> dict:
        return {
            'id':                self.id,
            'quotation_id':      self.quotation_id,
            'revision_no':       self.revision_no,
            'quotation_version': self.quotation_version,
            'docx_path':         self.docx_path,
            'pdf_path':          self.pdf_path,
            'template_name':     self.template_name,
            'copy_source':       self.copy_source,
            'grand_total':       float(self.grand_total) if self.grand_total is not None else None,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Proposal quotation={self.quotation_id} rev={self.revision_no}>'
