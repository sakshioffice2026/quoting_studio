"""Add tenant currency setting.

Revision ID: add_currency_setting
Revises: add_share_links, add_installation_installer_name
"""

from alembic import op
import sqlalchemy as sa


revision = 'add_currency_setting'
down_revision = ('add_share_links', 'add_installation_installer_name')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tenants',
        sa.Column('currency_code', sa.String(length=3), nullable=False, server_default='INR'),
    )


def downgrade():
    op.drop_column('tenants', 'currency_code')
