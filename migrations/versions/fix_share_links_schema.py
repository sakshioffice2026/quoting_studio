"""Recreate share_links with the schema used by app/models/share_link.py.

Revision ID: fix_share_links_schema
Revises: fcc48ad0b665
"""
from alembic import op
import sqlalchemy as sa


revision      = 'fix_share_links_schema'
down_revision = 'fcc48ad0b665'
branch_labels = None
depends_on    = None


def _create():
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


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if 'share_links' in inspector.get_table_names():
        columns = {c['name'] for c in inspector.get_columns('share_links')}
        if 'first_opened_at' in columns and 'response_action' in columns:
            return
        op.drop_table('share_links')

    _create()


def downgrade():
    pass
