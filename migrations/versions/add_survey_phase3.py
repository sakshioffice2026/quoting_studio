"""Add surveys and survey_openings tables (Phase 3 — Survey).

Revision ID: add_survey_phase3
Revises: add_preliminary_selection_phase2
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_survey_phase3'
down_revision = 'add_preliminary_selection_phase2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'surveys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('presel_id', sa.Integer(), sa.ForeignKey('preliminary_selections.id'), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('completed_date', sa.Date(), nullable=True),
        sa.Column('surveyor_name', sa.String(length=200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='SURVEY-SCHEDULED'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_surveys_tenant_id', 'surveys', ['tenant_id'])
    op.create_index('ix_surveys_lead_id', 'surveys', ['lead_id'])
    op.create_index('ix_surveys_project_id', 'surveys', ['project_id'])
    op.create_index('ix_surveys_presel_id', 'surveys', ['presel_id'])
    op.create_index('ix_surveys_status', 'surveys', ['status'])

    op.create_table(
        'survey_openings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('survey_id', sa.Integer(), sa.ForeignKey('surveys.id'), nullable=False),
        sa.Column('opening_label', sa.String(length=100), nullable=False),
        sa.Column('location_room', sa.String(length=200), nullable=True),
        sa.Column('measured_width_mm', sa.Integer(), nullable=True),
        sa.Column('measured_height_mm', sa.Integer(), nullable=True),
        sa.Column('wall_thickness_mm', sa.Integer(), nullable=True),
        sa.Column('sill_height_mm', sa.Integer(), nullable=True),
        sa.Column('site_condition_notes', sa.Text(), nullable=True),
        sa.Column('photo_refs', sa.Text(), nullable=True),
        sa.Column('site_issue_flags', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_survey_openings_tenant_id', 'survey_openings', ['tenant_id'])
    op.create_index('ix_survey_openings_survey_id', 'survey_openings', ['survey_id'])


def downgrade():
    op.drop_index('ix_survey_openings_survey_id', table_name='survey_openings')
    op.drop_index('ix_survey_openings_tenant_id', table_name='survey_openings')
    op.drop_table('survey_openings')

    op.drop_index('ix_surveys_status', table_name='surveys')
    op.drop_index('ix_surveys_presel_id', table_name='surveys')
    op.drop_index('ix_surveys_project_id', table_name='surveys')
    op.drop_index('ix_surveys_lead_id', table_name='surveys')
    op.drop_index('ix_surveys_tenant_id', table_name='surveys')
    op.drop_table('surveys')
