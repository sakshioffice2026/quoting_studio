"""Add master_quote_configs table (sections shown in the Master Quotation).

Revision ID: add_master_quote_config
Revises: add_currency_setting
Create Date: 2026-10-06 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_master_quote_config'
down_revision = 'add_currency_setting'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'master_quote_configs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('quotation_id', sa.Integer(), sa.ForeignKey('quotations.id'), nullable=True),
        sa.Column('sections_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'quotation_id', name='uq_master_cfg_tenant_quote'),
    )
    op.create_index('ix_master_quote_configs_tenant_id', 'master_quote_configs', ['tenant_id'])
    op.create_index('ix_master_quote_configs_quotation_id', 'master_quote_configs', ['quotation_id'])


def downgrade():
    op.drop_index('ix_master_quote_configs_quotation_id', table_name='master_quote_configs')
    op.drop_index('ix_master_quote_configs_tenant_id', table_name='master_quote_configs')
    op.drop_table('master_quote_configs')
