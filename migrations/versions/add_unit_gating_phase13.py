"""Unit-level payment gating: stage ledger on order_unit_releases.

Revision ID: add_unit_gating_phase13
Revises: add_visualisation_openings
Create Date: 2026-09-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_unit_gating_phase13'
down_revision = 'add_visualisation_openings'
branch_labels = None
depends_on    = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'order_unit_releases' not in _tables():
        op.create_table(
            'order_unit_releases',
            sa.Column('id',               sa.Integer(),     primary_key=True),
            sa.Column('tenant_id',        sa.Integer(),     sa.ForeignKey('tenants.id'),  nullable=False),
            sa.Column('order_id',         sa.Integer(),     sa.ForeignKey('orders.id'),   nullable=False),
            sa.Column('payment_id',       sa.Integer(),     sa.ForeignKey('payments.id'), nullable=False),
            sa.Column('window_id',        sa.Integer(),     sa.ForeignKey('windows.id', ondelete='SET NULL'), nullable=True),
            sa.Column('stage',            sa.String(30),    nullable=False, server_default='Advance'),
            sa.Column('stage_pct',        sa.Numeric(5, 2), nullable=False, server_default='0'),
            sa.Column('label',            sa.String(200),   nullable=True),
            sa.Column('unit_type',        sa.String(20),    nullable=False, server_default='window'),
            sa.Column('line_amount',      sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('required_advance', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('allocated_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('priority',         sa.Integer(),     nullable=False, server_default='0'),
            sa.Column('status',           sa.String(30),    nullable=False, server_default='UNIT-PENDING'),
            sa.Column('released_at',      sa.DateTime(),    nullable=True),
            sa.Column('created_at',       sa.DateTime(),    nullable=False),
            sa.Column('updated_at',       sa.DateTime(),    nullable=False),
        )
        op.create_index('ix_order_unit_releases_tenant_id',  'order_unit_releases', ['tenant_id'])
        op.create_index('ix_order_unit_releases_order_id',   'order_unit_releases', ['order_id'])
        op.create_index('ix_order_unit_releases_payment_id', 'order_unit_releases', ['payment_id'])
        op.create_index('ix_order_unit_releases_window_id',  'order_unit_releases', ['window_id'])
        op.create_index('ix_order_unit_releases_priority',   'order_unit_releases', ['priority'])
        op.create_index('ix_order_unit_releases_status',     'order_unit_releases', ['status'])
        op.create_index('ix_order_unit_releases_stage',      'order_unit_releases', ['stage'])
        return

    cols = _columns('order_unit_releases')
    if 'stage' not in cols:
        op.add_column('order_unit_releases',
                      sa.Column('stage', sa.String(30), nullable=False, server_default='Advance'))
        op.create_index('ix_order_unit_releases_stage', 'order_unit_releases', ['stage'])
    if 'stage_pct' not in cols:
        op.add_column('order_unit_releases',
                      sa.Column('stage_pct', sa.Numeric(5, 2), nullable=False, server_default='0'))


def downgrade():
    cols = _columns('order_unit_releases')
    if 'stage' in cols:
        op.drop_index('ix_order_unit_releases_stage', table_name='order_unit_releases')
        op.drop_column('order_unit_releases', 'stage')
    if 'stage_pct' in cols:
        op.drop_column('order_unit_releases', 'stage_pct')
