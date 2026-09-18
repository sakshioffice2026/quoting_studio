"""Add preliminary_selections table (Phase 2 — Preliminary Selection).

Revision ID: add_preliminary_selection_phase2
Revises: add_lead_customer_phase1
Create Date: 2026-09-18 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_preliminary_selection_phase2'
down_revision = 'add_lead_customer_phase1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'preliminary_selections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('shortlisted_ranges', sa.Text(), nullable=True),
        sa.Column('rough_opening_doors', sa.Integer(), nullable=True),
        sa.Column('rough_opening_windows', sa.Integer(), nullable=True),
        sa.Column('indicative_price_min', sa.Numeric(12, 2), nullable=True),
        sa.Column('indicative_price_max', sa.Numeric(12, 2), nullable=True),
        sa.Column('survey_required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PRESEL-IN_PROGRESS'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_preliminary_selections_tenant_id', 'preliminary_selections', ['tenant_id'])
    op.create_index('ix_preliminary_selections_lead_id', 'preliminary_selections', ['lead_id'])
    op.create_index('ix_preliminary_selections_project_id', 'preliminary_selections', ['project_id'])
    op.create_index('ix_preliminary_selections_status', 'preliminary_selections', ['status'])


def downgrade():
    op.drop_index('ix_preliminary_selections_status', table_name='preliminary_selections')
    op.drop_index('ix_preliminary_selections_project_id', table_name='preliminary_selections')
    op.drop_index('ix_preliminary_selections_lead_id', table_name='preliminary_selections')
    op.drop_index('ix_preliminary_selections_tenant_id', table_name='preliminary_selections')
    op.drop_table('preliminary_selections')
