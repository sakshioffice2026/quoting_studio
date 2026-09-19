"""Add design_approvals table + windows.design_locked/design_revision (Phase 4 — Design Approval).

Revision ID: add_design_approval_phase4
Revises: add_survey_phase3
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_design_approval_phase4'
down_revision = 'add_survey_phase3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('windows', sa.Column('design_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('windows', sa.Column('design_revision', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'design_approvals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('survey_id', sa.Integer(), sa.ForeignKey('surveys.id'), nullable=True),
        sa.Column('revision_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='DESIGN-DRAFT'),
        sa.Column('design_snapshot_json', sa.Text(), nullable=True),
        sa.Column('submitted_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('customer_signoff_notes', sa.Text(), nullable=True),
        sa.Column('revision_requested_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('revision_requested_at', sa.DateTime(), nullable=True),
        sa.Column('revision_requested_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_design_approvals_tenant_id', 'design_approvals', ['tenant_id'])
    op.create_index('ix_design_approvals_project_id', 'design_approvals', ['project_id'])
    op.create_index('ix_design_approvals_survey_id', 'design_approvals', ['survey_id'])
    op.create_index('ix_design_approvals_status', 'design_approvals', ['status'])


def downgrade():
    op.drop_index('ix_design_approvals_status', table_name='design_approvals')
    op.drop_index('ix_design_approvals_survey_id', table_name='design_approvals')
    op.drop_index('ix_design_approvals_project_id', table_name='design_approvals')
    op.drop_index('ix_design_approvals_tenant_id', table_name='design_approvals')
    op.drop_table('design_approvals')

    op.drop_column('windows', 'design_revision')
    op.drop_column('windows', 'design_locked')
