"""Add sent_at, sent_by, expires_at, approval_sla_days, resent_at, resent_by to design_approvals
   (Phase 4b — APPROVAL-SENT / APPROVAL-EXPIRED statuses).

Revision ID: add_design_approval_sent_expired
Revises: add_design_approval_phase4
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_design_approval_sent_expired'
down_revision = 'add_window_survey_opening_link'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('design_approvals',
        sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('design_approvals',
        sa.Column('sent_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('design_approvals',
        sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('design_approvals',
        sa.Column('approval_sla_days', sa.Integer(), nullable=False, server_default='10'))
    op.add_column('design_approvals',
        sa.Column('resent_at', sa.DateTime(), nullable=True))
    op.add_column('design_approvals',
        sa.Column('resent_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))

    # Index for the batch expiry job: filters on status + expires_at
    op.create_index(
        'ix_design_approvals_expires_at',
        'design_approvals',
        ['expires_at'],
    )


def downgrade():
    op.drop_index('ix_design_approvals_expires_at', table_name='design_approvals')
    op.drop_column('design_approvals', 'resent_by')
    op.drop_column('design_approvals', 'resent_at')
    op.drop_column('design_approvals', 'approval_sla_days')
    op.drop_column('design_approvals', 'expires_at')
    op.drop_column('design_approvals', 'sent_by')
    op.drop_column('design_approvals', 'sent_at')
