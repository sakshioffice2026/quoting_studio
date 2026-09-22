import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Tenant, ProjectType, TemplateQuestion
from app.models.template_question import InputType

app = create_app(os.environ.get('FLASK_ENV', 'development'))

PROJECT_TYPES = [
    {
        'tag': 'window',
        'name': 'Windows',
        'icon': '🪟',
        'description': 'New or replacement windows',
        'questions': [
            {
                'question_key': 'window_style',
                'label': 'What style of window are you looking for?',
                'input_type': InputType.CHIPS,
                'options': {'choices': ['Sliding', 'Casement', 'Fixed', 'Awning', 'Bay/Bow']},
                'maps_to_field': 'window_style',
            },
            {
                'question_key': 'rough_opening_count',
                'label': 'How many openings need windows?',
                'input_type': InputType.STEPPER,
                'options': {'min': 1, 'max': 30, 'default': 1},
                'maps_to_field': 'rough_opening_windows',
            },
            {
                'question_key': 'glazing',
                'label': 'What glazing do you prefer?',
                'input_type': InputType.CHIPS,
                'options': {'choices': ['Single', 'Double', 'Triple', 'Not sure']},
                'maps_to_field': 'glazing_type',
            },
        ],
    },
    {
        'tag': 'door',
        'name': 'Doors',
        'icon': '🚪',
        'description': 'Entry, patio, or interior doors',
        'questions': [
            {
                'question_key': 'door_type',
                'label': 'What type of door do you need?',
                'input_type': InputType.CHIPS,
                'options': {'choices': ['Entry', 'Patio/Sliding', 'French', 'Interior']},
                'maps_to_field': 'door_type',
            },
            {
                'question_key': 'door_count',
                'label': 'How many doors?',
                'input_type': InputType.STEPPER,
                'options': {'min': 1, 'max': 30, 'default': 1},
                'maps_to_field': 'rough_opening_doors',
            },
        ],
    },
]


def seed():
    with app.app_context():
        tenants = Tenant.query.all()
        if not tenants:
            print('No tenants found — nothing to seed.')
            return

        for tenant in tenants:
            for pt_data in PROJECT_TYPES:
                project_type = ProjectType.query.filter_by(
                    tenant_id=tenant.id, tag=pt_data['tag']
                ).first()

                if project_type:
                    project_type.name = pt_data['name']
                    project_type.icon = pt_data['icon']
                    project_type.description = pt_data['description']
                    project_type.is_active = True
                    print(f'[tenant={tenant.id}] Updated ProjectType "{pt_data["name"]}" (id={project_type.id})')
                else:
                    project_type = ProjectType(
                        tenant_id=tenant.id,
                        name=pt_data['name'],
                        icon=pt_data['icon'],
                        description=pt_data['description'],
                        tag=pt_data['tag'],
                        is_active=True,
                    )
                    db.session.add(project_type)
                    db.session.flush()
                    print(f'[tenant={tenant.id}] Created ProjectType "{pt_data["name"]}" (id={project_type.id})')

                for i, q in enumerate(pt_data['questions']):
                    question = TemplateQuestion.query.filter_by(
                        project_type_id=project_type.id, question_key=q['question_key']
                    ).first()

                    if question:
                        question.label = q['label']
                        question.input_type = q['input_type']
                        question.options = q['options']
                        question.step_order = i
                        question.is_optional = False
                        question.maps_to_field = q['maps_to_field']
                        print(f'  updated question "{q["question_key"]}"')
                    else:
                        question = TemplateQuestion(
                            project_type_id=project_type.id,
                            question_key=q['question_key'],
                            label=q['label'],
                            input_type=q['input_type'],
                            options=q['options'],
                            step_order=i,
                            is_optional=False,
                            maps_to_field=q['maps_to_field'],
                        )
                        db.session.add(question)
                        print(f'  created question "{q["question_key"]}"')

        db.session.commit()
        print('Seeding complete.')


if __name__ == '__main__':
    seed()
