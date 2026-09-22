"""Add dynamic requirement template tables (project_types, template_questions, template_responses) and leads.project_type_id.

Revision ID: req_templates_p12
Revises: add_project_customer_id
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'req_templates_p12'
down_revision = 'add_project_customer_id'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(table_name, index_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade():
    if not _table_exists('project_types'):
        op.create_table(
            'project_types',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('icon', sa.String(20), nullable=True),
            sa.Column('description', sa.String(300), nullable=True),
            sa.Column('tag', sa.String(60), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not _index_exists('project_types', 'idx_project_types_tenant'):
        op.create_index('idx_project_types_tenant', 'project_types', ['tenant_id'])

    if not _table_exists('template_questions'):
        op.create_table(
            'template_questions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('project_type_id', sa.Integer(), sa.ForeignKey('project_types.id', ondelete='CASCADE'), nullable=False),
            sa.Column('question_key', sa.String(80), nullable=False),
            sa.Column('label', sa.String(300), nullable=False),
            sa.Column('input_type', sa.String(20), nullable=False, server_default='chips'),
            sa.Column('options', sa.JSON(), nullable=True),
            sa.Column('step_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_optional', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('maps_to_field', sa.String(80), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not _index_exists('template_questions', 'idx_template_questions_type'):
        op.create_index('idx_template_questions_type', 'template_questions', ['project_type_id'])

    if not _table_exists('template_responses'):
        op.create_table(
            'template_responses',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False),
            sa.Column('project_type_id', sa.Integer(), sa.ForeignKey('project_types.id'), nullable=False),
            sa.Column('answers', sa.JSON(), nullable=True),
            sa.Column('is_submitted', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('submitted_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not _index_exists('template_responses', 'idx_template_responses_lead'):
        op.create_index('idx_template_responses_lead', 'template_responses', ['lead_id'])

    if not _index_exists('template_responses', 'idx_template_responses_tenant'):
        op.create_index('idx_template_responses_tenant', 'template_responses', ['tenant_id'])

    if not _column_exists('leads', 'project_type_id'):
        op.add_column('leads', sa.Column('project_type_id', sa.Integer(), sa.ForeignKey('project_types.id'), nullable=True))

    if not _index_exists('leads', 'idx_leads_project_type'):
        op.create_index('idx_leads_project_type', 'leads', ['project_type_id'])


def downgrade():
    if _index_exists('leads', 'idx_leads_project_type'):
        op.drop_index('idx_leads_project_type', table_name='leads')

    if _column_exists('leads', 'project_type_id'):
        op.drop_column('leads', 'project_type_id')

    if _index_exists('template_responses', 'idx_template_responses_tenant'):
        op.drop_index('idx_template_responses_tenant', table_name='template_responses')

    if _index_exists('template_responses', 'idx_template_responses_lead'):
        op.drop_index('idx_template_responses_lead', table_name='template_responses')

    if _table_exists('template_responses'):
        op.drop_table('template_responses')

    if _index_exists('template_questions', 'idx_template_questions_type'):
        op.drop_index('idx_template_questions_type', table_name='template_questions')

    if _table_exists('template_questions'):
        op.drop_table('template_questions')

    if _index_exists('project_types', 'idx_project_types_tenant'):
        op.drop_index('idx_project_types_tenant', table_name='project_types')

    if _table_exists('project_types'):
        op.drop_table('project_types')
