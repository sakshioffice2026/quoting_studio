"""Add manufacturing_jobs table (Phase 8 — Manufacturing).

Revision ID: add_manufacturing_phase8
Revises: add_payment_phase7
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_manufacturing_phase8'
down_revision = 'add_payment_phase7'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'manufacturing_jobs',
        sa.Column('id',                       sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',                sa.Integer(),   sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('order_id',                 sa.Integer(),   sa.ForeignKey('orders.id'),  nullable=False),
        sa.Column('opening_id',               sa.Integer(),   sa.ForeignKey('windows.id'), nullable=False),
        sa.Column('job_number',               sa.String(40),  unique=True, nullable=False),
        sa.Column('status',                   sa.String(40),  nullable=False, server_default='MFG-QUEUED'),
        sa.Column('production_stage',         sa.String(30),  nullable=False, server_default='Cutting'),
        sa.Column('profile_codes_json',       sa.Text(),      nullable=True),
        sa.Column('material_batch_ref',       sa.String(100), nullable=True),
        sa.Column('qc_result',                sa.String(20),  nullable=True),
        sa.Column('qc_notes',                 sa.Text(),      nullable=True),
        sa.Column('qc_checked_by',            sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('qc_checked_at',            sa.DateTime(),  nullable=True),
        sa.Column('planned_completion_date',  sa.Date(),      nullable=True),
        sa.Column('actual_completion_date',   sa.Date(),      nullable=True),
        sa.Column('assigned_to',              sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',               sa.DateTime(),  nullable=False),
        sa.Column('updated_at',               sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_manufacturing_jobs_tenant_id',  'manufacturing_jobs', ['tenant_id'])
    op.create_index('ix_manufacturing_jobs_order_id',   'manufacturing_jobs', ['order_id'])
    op.create_index('ix_manufacturing_jobs_opening_id', 'manufacturing_jobs', ['opening_id'])
    op.create_index('ix_manufacturing_jobs_status',     'manufacturing_jobs', ['status'])


def downgrade():
    op.drop_index('ix_manufacturing_jobs_status',     table_name='manufacturing_jobs')
    op.drop_index('ix_manufacturing_jobs_opening_id', table_name='manufacturing_jobs')
    op.drop_index('ix_manufacturing_jobs_order_id',   table_name='manufacturing_jobs')
    op.drop_index('ix_manufacturing_jobs_tenant_id',  table_name='manufacturing_jobs')
    op.drop_table('manufacturing_jobs')
