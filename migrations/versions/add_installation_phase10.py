"""Add installations and installation_items tables (Phase 10 — Installation).

Revision ID: add_installation_phase10
Revises: add_delivery_phase9
Create Date: 2026-09-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_installation_phase10'
down_revision = 'add_delivery_phase9'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'installations',
        sa.Column('id',                   sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',            sa.Integer(),   sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('order_id',             sa.Integer(),   sa.ForeignKey('orders.id'),  nullable=False),
        sa.Column('install_number',       sa.String(40),  unique=True, nullable=False),
        sa.Column('status',               sa.String(40),  nullable=False, server_default='INSTALL-SCHEDULED'),
        sa.Column('installation_address', sa.Text(),      nullable=True),
        sa.Column('site_contact_name',    sa.String(200), nullable=True),
        sa.Column('site_contact_phone',   sa.String(50),  nullable=True),
        sa.Column('team_lead_name',       sa.String(200), nullable=True),
        sa.Column('scheduled_date',       sa.Date(),      nullable=True),
        sa.Column('started_at',           sa.DateTime(),  nullable=True),
        sa.Column('completed_at',         sa.DateTime(),  nullable=True),
        sa.Column('customer_signoff_at',  sa.DateTime(),  nullable=True),
        sa.Column('signed_by',            sa.String(200), nullable=True),
        sa.Column('handover_notes',       sa.Text(),      nullable=True),
        sa.Column('handover_file_path',   sa.String(500), nullable=True),
        sa.Column('assigned_to',          sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_by',           sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',           sa.DateTime(),  nullable=False),
        sa.Column('updated_at',           sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_installations_tenant_id', 'installations', ['tenant_id'])
    op.create_index('ix_installations_order_id',  'installations', ['order_id'])
    op.create_index('ix_installations_status',    'installations', ['status'])

    op.create_table(
        'installation_items',
        sa.Column('id',                     sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',              sa.Integer(),   sa.ForeignKey('tenants.id'),         nullable=False),
        sa.Column('installation_id',        sa.Integer(),   sa.ForeignKey('installations.id'),   nullable=False),
        sa.Column('opening_id',             sa.Integer(),   sa.ForeignKey('windows.id'),         nullable=False),
        sa.Column('delivery_item_id',       sa.Integer(),   sa.ForeignKey('delivery_items.id'),  nullable=True),
        sa.Column('installed_by',           sa.String(200), nullable=True),
        sa.Column('install_date',           sa.DateTime(),  nullable=True),
        sa.Column('fitted',                 sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('hardware_adjusted',      sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('joints_sealed',          sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('site_cleaned',           sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('functional_test_result', sa.String(20),  nullable=False, server_default='Pending'),
        sa.Column('snag_list',              sa.Text(),      nullable=True),
        sa.Column('snag_resolved',          sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('created_at',             sa.DateTime(),  nullable=False),
        sa.Column('updated_at',             sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_installation_items_tenant_id',       'installation_items', ['tenant_id'])
    op.create_index('ix_installation_items_installation_id', 'installation_items', ['installation_id'])
    op.create_index('ix_installation_items_opening_id',      'installation_items', ['opening_id'])
    op.create_index('ix_installation_items_test_result',     'installation_items', ['functional_test_result'])


def downgrade():
    op.drop_index('ix_installation_items_test_result',       table_name='installation_items')
    op.drop_index('ix_installation_items_opening_id',        table_name='installation_items')
    op.drop_index('ix_installation_items_installation_id',   table_name='installation_items')
    op.drop_index('ix_installation_items_tenant_id',         table_name='installation_items')
    op.drop_table('installation_items')

    op.drop_index('ix_installations_status',    table_name='installations')
    op.drop_index('ix_installations_order_id',  table_name='installations')
    op.drop_index('ix_installations_tenant_id', table_name='installations')
    op.drop_table('installations')
