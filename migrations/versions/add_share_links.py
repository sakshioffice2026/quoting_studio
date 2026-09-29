"""add share_links table

Revision ID: add_share_links
Revises: add_unit_gating_phase13
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_share_links'
down_revision = 'add_unit_gating_phase13'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'share_links',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('resource_type', sa.String(30), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('first_opened_at', sa.DateTime(), nullable=True),
        sa.Column('last_opened_at', sa.DateTime(), nullable=True),
        sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.Column('response_action', sa.String(30), nullable=True),
    )
    op.create_index('ix_share_links_tenant_id', 'share_links', ['tenant_id'])
    op.create_index('ix_share_links_token', 'share_links', ['token'], unique=True)
    op.create_index('ix_share_links_resource', 'share_links', ['resource_type', 'resource_id'])


def downgrade():
    op.drop_index('ix_share_links_resource', table_name='share_links')
    op.drop_index('ix_share_links_token', table_name='share_links')
    op.drop_index('ix_share_links_tenant_id', table_name='share_links')
    op.drop_table('share_links')
