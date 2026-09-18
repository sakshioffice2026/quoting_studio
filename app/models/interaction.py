from datetime import datetime
from ..extensions import db


class InteractionType:
    CALL     = 'call'
    WHATSAPP = 'whatsapp'
    EMAIL    = 'email'
    VISIT    = 'visit'

    ALL = [CALL, WHATSAPP, EMAIL, VISIT]


class InteractionOutcome:
    CONNECTED           = 'connected'
    NO_ANSWER           = 'no-answer'
    NOT_INTERESTED      = 'not-interested'
    CALLBACK_REQUESTED  = 'callback-requested'

    ALL = [CONNECTED, NO_ANSWER, NOT_INTERESTED, CALLBACK_REQUESTED]


class QualificationScore:
    HOT  = 'Hot'
    WARM = 'Warm'
    COLD = 'Cold'

    ALL = [HOT, WARM, COLD]


class Interaction(db.Model):
    __tablename__ = 'interactions'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    lead_id    = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    interaction_type    = db.Column(db.String(20), nullable=False)
    outcome              = db.Column(db.String(30), nullable=True)
    notes                 = db.Column(db.Text, nullable=True)
    next_action_date      = db.Column(db.Date, nullable=True)
    qualification_score   = db.Column(db.String(10), nullable=True)
    lost_reason           = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id':                  self.id,
            'tenant_id':           self.tenant_id,
            'lead_id':             self.lead_id,
            'created_by':          self.created_by,
            'interaction_type':    self.interaction_type,
            'outcome':             self.outcome,
            'notes':               self.notes,
            'next_action_date':    self.next_action_date.isoformat() if self.next_action_date else None,
            'qualification_score': self.qualification_score,
            'lost_reason':         self.lost_reason,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Interaction {self.interaction_type} lead={self.lead_id}>'
