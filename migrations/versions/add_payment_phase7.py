"""Add payments table (Phase 7 — Advance Payment / Payment Journey).

Revision ID: add_payment_phase7
Revises: add_order_phase6
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_payment_phase7'
down_revision = 'add_order_phase6'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'payments',
        sa.Column('id',                sa.Integer(),     primary_key=True),
        sa.Column('tenant_id',         sa.Integer(),     sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('order_id',          sa.Integer(),     sa.ForeignKey('orders.id'),  nullable=False),
        sa.Column('payment_number',    sa.String(40),    unique=True, nullable=False),
        sa.Column('payment_stage',     sa.String(30),    nullable=False, server_default='Advance'),
        sa.Column('status',            sa.String(40),    nullable=False, server_default='PAY-INVOICED'),
        sa.Column('invoice_amount',    sa.Numeric(12,2), nullable=False),
        sa.Column('amount_received',   sa.Numeric(12,2), nullable=False, server_default='0'),
        sa.Column('due_date',          sa.Date(),        nullable=True),
        sa.Column('payment_mode',      sa.String(50),    nullable=True),
        sa.Column('transaction_ref',   sa.String(100),   nullable=True),
        sa.Column('received_at',       sa.DateTime(),    nullable=True),
        sa.Column('hold_flag',         sa.Boolean(),     nullable=False, server_default=sa.false()),
        sa.Column('hold_reason',       sa.Text(),        nullable=True),
        sa.Column('invoice_file_path', sa.String(500),   nullable=True),
        sa.Column('receipt_file_path', sa.String(500),   nullable=True),
        sa.Column('raised_by',         sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',        sa.DateTime(),    nullable=False),
        sa.Column('updated_at',        sa.DateTime(),    nullable=False),
    )
    op.create_index('ix_payments_tenant_id', 'payments', ['tenant_id'])
    op.create_index('ix_payments_order_id',  'payments', ['order_id'])
    op.create_index('ix_payments_status',    'payments', ['status'])


def downgrade():
    op.drop_index('ix_payments_status',    table_name='payments')
    op.drop_index('ix_payments_order_id',  table_name='payments')
    op.drop_index('ix_payments_tenant_id', table_name='payments')
    op.drop_table('payments')
