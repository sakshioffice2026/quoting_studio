from datetime import datetime

from ..extensions import db


class VisualFeedbackKind:
    APPROVED       = 'APPROVED'         # customer approved an item (or the whole quote)
    CHANGE_REQUEST = 'CHANGE_REQUEST'   # customer comment asking for a change
    STAFF_REPLY    = 'STAFF_REPLY'      # salesperson reply on a change request

    ALL = [APPROVED, CHANGE_REQUEST, STAFF_REPLY]


class VisualFeedbackStatus:
    OPEN        = 'OPEN'         # change request waiting for the salesperson
    RESOLVED    = 'RESOLVED'     # handled by the salesperson
    ACTIVE      = 'ACTIVE'       # approval that still matches the current item
    SUPERSEDED  = 'SUPERSEDED'   # approval invalidated because the item changed

    ALL = [OPEN, RESOLVED, ACTIVE, SUPERSEDED]


class VisualFeedback(db.Model):
    """Customer response to the rendered preview of a quotation.

    Rows are per line item (line_id) or, when line_id is NULL, for the whole
    quotation. An approval records item_hash, a fingerprint of the item as the
    customer saw it. If the salesperson later changes the item the hash no
    longer matches and the approval is treated as superseded.
    """

    __tablename__ = 'visual_feedback'

    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    quotation_id  = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False, index=True)
    share_link_id = db.Column(db.Integer, db.ForeignKey('share_links.id'), nullable=True, index=True)

    line_id       = db.Column(db.Integer, nullable=True)        # NULL = whole quotation
    kind          = db.Column(db.String(20), nullable=False)
    status        = db.Column(db.String(20), nullable=False)
    comment       = db.Column(db.Text, nullable=True)
    item_hash     = db.Column(db.String(64), nullable=True)     # fingerprint of the item at approval

    author_name   = db.Column(db.String(120), nullable=True)    # customer name shown on the link
    author_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # staff replies

    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at   = db.Column(db.DateTime, nullable=True)
    resolved_by   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    superseded_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_visual_feedback_quote_line', 'quotation_id', 'line_id'),
        db.Index('ix_visual_feedback_quote_status', 'quotation_id', 'status'),
    )

    @property
    def is_open(self) -> bool:
        return self.kind == VisualFeedbackKind.CHANGE_REQUEST and \
            self.status == VisualFeedbackStatus.OPEN

    @property
    def is_active_approval(self) -> bool:
        return self.kind == VisualFeedbackKind.APPROVED and \
            self.status == VisualFeedbackStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            'id':          self.id,
            'line_id':     self.line_id,
            'kind':        self.kind,
            'status':      self.status,
            'comment':     self.comment,
            'author_name': self.author_name,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
        }
