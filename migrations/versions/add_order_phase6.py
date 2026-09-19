"""Add orders table (Phase 6 — Order Acceptance).

Revision ID: add_order_phase6
Revises: add_quotation_phase5
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_order_phase6'
down_revision = 'add_quotation_phase5'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'orders',
        sa.Column('id',                        sa.Integer(),     primary_key=True),
        sa.Column('tenant_id',                  sa.Integer(),     sa.ForeignKey('tenants.id'),    nullable=False),
        sa.Column('project_id',                 sa.Integer(),     sa.ForeignKey('projects.id'),   nullable=False),
        sa.Column('quotation_id',               sa.Integer(),     sa.ForeignKey('quotations.id'), nullable=False),
        sa.Column('order_number',               sa.String(40),    unique=True, nullable=False),
        sa.Column('contract_ref',               sa.String(100),   nullable=True),
        sa.Column('status',                     sa.String(40),    nullable=False, server_default='ORDER-PENDING_SIGNATURE'),
        sa.Column('order_confirmed_by_name',    sa.String(200),   nullable=True),
        sa.Column('order_confirmed_at',         sa.DateTime(),    nullable=True),
        sa.Column('confirmation_method',        sa.String(50),    nullable=True),
        sa.Column('assigned_project_manager',   sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('promised_delivery_date',     sa.Date(),        nullable=True),
        sa.Column('total_amount',               sa.Numeric(12,2), nullable=True),
        sa.Column('cancelled_at',               sa.DateTime(),    nullable=True),
        sa.Column('cancelled_reason',           sa.Text(),        nullable=True),
        sa.Column('contract_file_path',         sa.String(500),   nullable=True),
        sa.Column('created_by',                 sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',                 sa.DateTime(),    nullable=False),
        sa.Column('updated_at',                 sa.DateTime(),    nullable=False),
    )
    op.create_index('ix_orders_tenant_id',    'orders', ['tenant_id'])
    op.create_index('ix_orders_project_id',   'orders', ['project_id'])
    op.create_index('ix_orders_quotation_id', 'orders', ['quotation_id'])
    op.create_index('ix_orders_status',       'orders', ['status'])


def downgrade():
    op.drop_index('ix_orders_status',       table_name='orders')
    op.drop_index('ix_orders_quotation_id', table_name='orders')
    op.drop_index('ix_orders_project_id',   table_name='orders')
    op.drop_index('ix_orders_tenant_id',    table_name='orders')
    op.drop_table('orders')
