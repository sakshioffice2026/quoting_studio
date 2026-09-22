"""Seed ProjectType + TemplateQuestion data, including material & color questions
that requirement_template_service.get_summary() looks for.
Run from project root: python seed_requirement_templates.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.project_type import ProjectType
from app.models.template_question import TemplateQuestion, InputType

TENANT_ID = 1   # <- adjust tenant id

MATERIAL_OPTIONS = ['uPVC', 'Aluminium', 'Wood', 'Wood-Aluminium']
COLOR_OPTIONS = ['White', 'Black', 'Grey', 'Wood Finish', 'Custom (tell us)']

PROJECT_TYPES = [
    {
        'name': 'Windows',
        'icon': '🪟',
        'description': 'Window openings for any property type',
        'tag': 'windows',
        'questions': [
            {
                'question_key': 'window_count',
                'label': 'How many windows roughly?',
                'input_type': InputType.STEPPER,
                'options': {'min': 1, 'max': 50, 'default': 6, 'unit': 'windows'},
                'step_order': 1,
                'is_optional': False,
                'maps_to_field': 'rough_opening_windows',
            },
            {
                'question_key': 'material',
                'label': 'Which material do you prefer?',
                'input_type': InputType.CHIPS,
                'options': {'choices': MATERIAL_OPTIONS},
                'step_order': 2,
                'is_optional': False,
                'maps_to_field': 'material',
            },
            {
                'question_key': 'color',
                'label': 'Which color / finish?',
                'input_type': InputType.CHIPS,
                'options': {'choices': COLOR_OPTIONS},
                'step_order': 3,
                'is_optional': False,
                'maps_to_field': 'color',
            },
            {
                'question_key': 'window_features',
                'label': 'Anything important to you?',
                'input_type': InputType.CHIPS,
                'options': {'choices': [
                    'Soundproofing', 'Mosquito Mesh', 'Security Locks', 'Large glass panels',
                ]},
                'step_order': 4,
                'is_optional': False,
                'maps_to_field': 'shortlisted_ranges',
            },
            {
                'question_key': 'additional_notes',
                'label': 'Anything else you want to tell us?',
                'input_type': InputType.TEXT,
                'options': None,
                'step_order': 5,
                'is_optional': True,
                'maps_to_field': 'notes',
            },
        ],
    },
    {
        'name': 'Doors',
        'icon': '🚪',
        'description': 'Door openings for any property type',
        'tag': 'doors',
        'questions': [
            {
                'question_key': 'door_count',
                'label': 'How many doors roughly?',
                'input_type': InputType.STEPPER,
                'options': {'min': 1, 'max': 30, 'default': 2, 'unit': 'doors'},
                'step_order': 1,
                'is_optional': False,
                'maps_to_field': 'rough_opening_doors',
            },
            {
                'question_key': 'material',
                'label': 'Which material do you prefer?',
                'input_type': InputType.CHIPS,
                'options': {'choices': MATERIAL_OPTIONS},
                'step_order': 2,
                'is_optional': False,
                'maps_to_field': 'material',
            },
            {
                'question_key': 'color',
                'label': 'Which color / finish?',
                'input_type': InputType.CHIPS,
                'options': {'choices': COLOR_OPTIONS},
                'step_order': 3,
                'is_optional': False,
                'maps_to_field': 'color',
            },
            {
                'question_key': 'door_features',
                'label': 'Anything important to you?',
                'input_type': InputType.CHIPS,
                'options': {'choices': [
                    'Heavy-duty sliding', 'Automatic entry', 'Security Locks', 'Wood-look finish',
                ]},
                'step_order': 4,
                'is_optional': False,
                'maps_to_field': 'shortlisted_ranges',
            },
            {
                'question_key': 'additional_notes',
                'label': 'Anything else you want to tell us?',
                'input_type': InputType.TEXT,
                'options': None,
                'step_order': 5,
                'is_optional': True,
                'maps_to_field': 'notes',
            },
        ],
    },
]


def run():
    app = create_app(os.environ.get('FLASK_ENV', 'production'))
    with app.app_context():
        for pt_data in PROJECT_TYPES:
            questions = pt_data.pop('questions')
            pt = ProjectType.query.filter_by(tenant_id=TENANT_ID, name=pt_data['name']).first()
            if not pt:
                pt = ProjectType(tenant_id=TENANT_ID, **pt_data)
                db.session.add(pt)
                db.session.flush()
                print(f'Created ProjectType: {pt.name} (id={pt.id})')
            else:
                for k, v in pt_data.items():
                    setattr(pt, k, v)
                print(f'Updated ProjectType: {pt.name} (id={pt.id})')

            for q_data in questions:
                q = TemplateQuestion.query.filter_by(
                    project_type_id=pt.id, question_key=q_data['question_key']
                ).first()
                if not q:
                    q = TemplateQuestion(project_type_id=pt.id, **q_data)
                    db.session.add(q)
                    print(f'  + question: {q_data["question_key"]}')
                else:
                    for k, v in q_data.items():
                        setattr(q, k, v)
                    print(f'  ~ question: {q_data["question_key"]}')

            pt_data['questions'] = questions  # restore for idempotent re-run

        db.session.commit()
        print('Seed complete.')


if __name__ == '__main__':
    run()
