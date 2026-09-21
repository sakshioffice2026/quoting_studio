"""Add deliveries and delivery_items tables (Phase 9 — Delivery).

Revision ID: add_delivery_phase9
Revises: add_manufacturing_phase8
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_delivery_phase9'
down_revision = 'add_manufacturing_phase8'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'deliveries',
        sa.Column('id',                      sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',               sa.Integer(),   sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('order_id',                sa.Integer(),   sa.ForeignKey('orders.id'),  nullable=False),
        sa.Column('delivery_number',         sa.String(40),  unique=True, nullable=False),
        sa.Column('challan_number',          sa.String(40),  nullable=True),
        sa.Column('status',                  sa.String(40),  nullable=False, server_default='DEL-PACKED'),
        sa.Column('delivery_address',        sa.Text(),      nullable=True),
        sa.Column('site_contact_name',       sa.String(200), nullable=True),
        sa.Column('site_contact_phone',      sa.String(50),  nullable=True),
        sa.Column('packed_at',               sa.DateTime(),  nullable=True),
        sa.Column('packed_by',               sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('scheduled_dispatch_date', sa.Date(),      nullable=True),
        sa.Column('dispatch_date',           sa.DateTime(),  nullable=True),
        sa.Column('vehicle_ref',             sa.String(100), nullable=True),
        sa.Column('transporter_name',        sa.String(200), nullable=True),
        sa.Column('driver_name',             sa.String(200), nullable=True),
        sa.Column('driver_phone',            sa.String(50),  nullable=True),
        sa.Column('delivered_at',            sa.DateTime(),  nullable=True),
        sa.Column('received_by',             sa.String(200), nullable=True),
        sa.Column('damage_shortage_notes',   sa.Text(),      nullable=True),
        sa.Column('pod_file_path',           sa.String(500), nullable=True),
        sa.Column('assigned_to',             sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_by',              sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',              sa.DateTime(),  nullable=False),
        sa.Column('updated_at',              sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_deliveries_tenant_id', 'deliveries', ['tenant_id'])
    op.create_index('ix_deliveries_order_id',  'deliveries', ['order_id'])
    op.create_index('ix_deliveries_status',    'deliveries', ['status'])

    op.create_table(
        'delivery_items',
        sa.Column('id',                   sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',            sa.Integer(),   sa.ForeignKey('tenants.id'),            nullable=False),
        sa.Column('delivery_id',          sa.Integer(),   sa.ForeignKey('deliveries.id'),         nullable=False),
        sa.Column('opening_id',           sa.Integer(),   sa.ForeignKey('windows.id'),            nullable=False),
        sa.Column('manufacturing_job_id', sa.Integer(),   sa.ForeignKey('manufacturing_jobs.id'), nullable=True),
        sa.Column('package_label',        sa.String(100), nullable=True),
        sa.Column('package_count',        sa.Integer(),   nullable=False, server_default='1'),
        sa.Column('is_damaged',           sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('is_short',             sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('issue_notes',          sa.Text(),      nullable=True),
        sa.Column('issue_resolved',       sa.Boolean(),   nullable=False, server_default=sa.false()),
        sa.Column('created_at',           sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_delivery_items_tenant_id',   'delivery_items', ['tenant_id'])
    op.create_index('ix_delivery_items_delivery_id', 'delivery_items', ['delivery_id'])
    op.create_index('ix_delivery_items_opening_id',  'delivery_items', ['opening_id'])


def downgrade():
    op.drop_index('ix_delivery_items_opening_id',  table_name='delivery_items')
    op.drop_index('ix_delivery_items_delivery_id', table_name='delivery_items')
    op.drop_index('ix_delivery_items_tenant_id',   table_name='delivery_items')
    op.drop_table('delivery_items')

    op.drop_index('ix_deliveries_status',    table_name='deliveries')
    op.drop_index('ix_deliveries_order_id',  table_name='deliveries')
    op.drop_index('ix_deliveries_tenant_id', table_name='deliveries')
    op.drop_table('deliveries')
