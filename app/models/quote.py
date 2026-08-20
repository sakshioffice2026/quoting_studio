from datetime import datetime, date
from ..extensions import db


class Quote(db.Model):
    __tablename__ = 'quotes'

    id              = db.Column(db.Integer, primary_key=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'),  nullable=False, index=True)
    quote_number    = db.Column(db.String(40), unique=True, nullable=False)
    issued_date     = db.Column(db.Date,     default=date.today, nullable=False)
    subtotal        = db.Column(db.Numeric(10, 2), nullable=True)
    vat_rate        = db.Column(db.Float, default=0.20)
    total           = db.Column(db.Numeric(10, 2), nullable=True)
    pdf_path        = db.Column(db.String(500), nullable=True)
    sent_at         = db.Column(db.DateTime, nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    revision        = db.Column(db.Integer, default=1, nullable=False)
    parent_quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'), nullable=True, index=True)

    parent = db.relationship(
        'Quote',
        primaryjoin='Quote.parent_quote_id == Quote.id',
        foreign_keys='Quote.parent_quote_id',
        remote_side='Quote.id',
        backref=db.backref('revisions', lazy='dynamic'),
    )

    @staticmethod
    def generate_number(tenant_id: int) -> str:
        """Race-safe quote number. Fetches all existing numbers for this prefix
        and takes the Python-side MAX — avoids COUNT race condition where two
        concurrent requests both see N and both try to insert N+1."""
        today = date.today()
        prefix = f"QS-{today.strftime('%Y%m')}"
        existing = [
            q.quote_number for q in
            Quote.query.filter(
                Quote.tenant_id == tenant_id,
                Quote.quote_number.like(f"{prefix}-%")
            ).with_entities(Quote.quote_number).all()
        ]
        last = 0
        for num in existing:
            try:
                last = max(last, int(num.rsplit('-', 1)[-1]))
            except (ValueError, IndexError):
                pass
        return f"{prefix}-{str(last + 1).zfill(3)}"

    @property
    def is_sent(self):
        return self.sent_at is not None

    @property
    def vat_amount(self):
        if self.subtotal:
            return round(float(self.subtotal) * self.vat_rate, 2)
        return 0.0

    def __repr__(self):
        return f'<Quote {self.quote_number} rev={self.revision}>'