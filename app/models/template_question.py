from datetime import datetime
from ..extensions import db


class InputType:
    CHIPS   = 'chips'
    STEPPER = 'stepper'
    SLIDER  = 'slider'
    TEXT    = 'text'
    CARDS   = 'cards'

    ALL = [CHIPS, STEPPER, SLIDER, TEXT, CARDS]


class TemplateQuestion(db.Model):
    __tablename__ = 'template_questions'

    id              = db.Column(db.Integer, primary_key=True)
    project_type_id = db.Column(db.Integer, db.ForeignKey('project_types.id'), nullable=False, index=True)

    question_key  = db.Column(db.String(80), nullable=False)
    label         = db.Column(db.String(300), nullable=False)
    input_type    = db.Column(db.String(20), nullable=False, default=InputType.CHIPS)
    options       = db.Column(db.JSON, nullable=True)
    step_order    = db.Column(db.Integer, nullable=False, default=0)
    is_optional   = db.Column(db.Boolean, nullable=False, default=False)
    maps_to_field = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id':              self.id,
            'project_type_id': self.project_type_id,
            'question_key':    self.question_key,
            'label':           self.label,
            'input_type':      self.input_type,
            'options':         self.options,
            'step_order':      self.step_order,
            'is_optional':     self.is_optional,
            'maps_to_field':   self.maps_to_field,
        }

    def __repr__(self):
        return f'<TemplateQuestion {self.question_key} type={self.project_type_id}>'
