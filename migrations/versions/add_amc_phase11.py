"""Add warranties, amc_contracts and service_tickets tables (Phase 11 — AMC).

Revision ID: add_amc_phase11
Revises: add_installation_phase10
Create Date: 2026-09-21 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_amc_phase11'
down_revision = 'add_installation_phase10'
branch_labels = None
depends_on    = None


def upgrade():
    # ---------------------------------------------------------------- #
    #  warranties
    # ---------------------------------------------------------------- #
    op.create_table(
        'warranties',
        sa.Column('id',                  sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',           sa.Integer(),   sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('order_id',            sa.Integer(),   sa.ForeignKey('orders.id'),  nullable=False, unique=True),
        sa.Column('warranty_number',     sa.String(40),  unique=True, nullable=False),
        sa.Column('status',              sa.String(40),  nullable=False, server_default='WARRANTY-ACTIVE'),
        sa.Column('warranty_months',     sa.Integer(),   nullable=False, server_default='12'),
        sa.Column('warranty_start_date', sa.Date(),      nullable=False),
        sa.Column('warranty_end_date',   sa.Date(),      nullable=False),
        sa.Column('terms',               sa.Text(),      nullable=True),
        sa.Column('created_by',          sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',          sa.DateTime(),  nullable=False),
        sa.Column('updated_at',          sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_warranties_tenant_id', 'warranties', ['tenant_id'])
    op.create_index('ix_warranties_order_id',  'warranties', ['order_id'])
    op.create_index('ix_warranties_status',    'warranties', ['status'])

    # ---------------------------------------------------------------- #
    #  amc_contracts
    # ---------------------------------------------------------------- #
    op.create_table(
        'amc_contracts',
        sa.Column('id',                 sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',          sa.Integer(),   sa.ForeignKey('tenants.id'),       nullable=False),
        sa.Column('order_id',           sa.Integer(),   sa.ForeignKey('orders.id'),        nullable=False),
        sa.Column('warranty_id',        sa.Integer(),   sa.ForeignKey('warranties.id'),    nullable=True),
        sa.Column('renewal_of_id',      sa.Integer(),   sa.ForeignKey('amc_contracts.id'), nullable=True),
        sa.Column('amc_number',         sa.String(40),  unique=True, nullable=False),
        sa.Column('status',             sa.String(40),  nullable=False, server_default='AMC-OFFERED'),
        sa.Column('plan_tier',          sa.String(20),  nullable=False, server_default='Basic'),
        sa.Column('visits_per_year',    sa.Integer(),   nullable=False, server_default='1'),
        sa.Column('annual_fee',         sa.Numeric(12, 2), nullable=True),
        sa.Column('offered_at',         sa.DateTime(),  nullable=True),
        sa.Column('amc_start_date',     sa.Date(),      nullable=True),
        sa.Column('amc_end_date',       sa.Date(),      nullable=True),
        sa.Column('activated_at',       sa.DateTime(),  nullable=True),
        sa.Column('signed_by',          sa.String(200), nullable=True),
        sa.Column('contract_file_path', sa.String(500), nullable=True),
        sa.Column('notes',              sa.Text(),      nullable=True),
        sa.Column('created_by',         sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',         sa.DateTime(),  nullable=False),
        sa.Column('updated_at',         sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_amc_contracts_tenant_id', 'amc_contracts', ['tenant_id'])
    op.create_index('ix_amc_contracts_order_id',  'amc_contracts', ['order_id'])
    op.create_index('ix_amc_contracts_status',    'amc_contracts', ['status'])

    # ---------------------------------------------------------------- #
    #  service_tickets
    # ---------------------------------------------------------------- #
    op.create_table(
        'service_tickets',
        sa.Column('id',               sa.Integer(),   primary_key=True),
        sa.Column('tenant_id',        sa.Integer(),   sa.ForeignKey('tenants.id'),       nullable=False),
        sa.Column('order_id',         sa.Integer(),   sa.ForeignKey('orders.id'),        nullable=False),
        sa.Column('opening_id',       sa.Integer(),   sa.ForeignKey('windows.id'),       nullable=True),
        sa.Column('amc_contract_id',  sa.Integer(),   sa.ForeignKey('amc_contracts.id'), nullable=True),
        sa.Column('ticket_number',    sa.String(40),  unique=True, nullable=False),
        sa.Column('service_type',     sa.String(20),  nullable=False, server_default='Complaint'),
        sa.Column('status',           sa.String(40),  nullable=False, server_default='TICKET-OPEN'),
        sa.Column('coverage',         sa.String(20),  nullable=False, server_default='Chargeable'),
        sa.Column('title',            sa.String(200), nullable=False),
        sa.Column('description',      sa.Text(),      nullable=True),
        sa.Column('reported_by',      sa.String(200), nullable=True),
        sa.Column('scheduled_date',   sa.Date(),      nullable=True),
        sa.Column('technician_name',  sa.String(200), nullable=True),
        sa.Column('started_at',       sa.DateTime(),  nullable=True),
        sa.Column('resolution_notes', sa.Text(),      nullable=True),
        sa.Column('resolved_at',      sa.DateTime(),  nullable=True),
        sa.Column('resolved_by',      sa.String(200), nullable=True),
        sa.Column('opened_at',        sa.DateTime(),  nullable=False),
        sa.Column('created_by',       sa.Integer(),   sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',       sa.DateTime(),  nullable=False),
        sa.Column('updated_at',       sa.DateTime(),  nullable=False),
    )
    op.create_index('ix_service_tickets_tenant_id',       'service_tickets', ['tenant_id'])
    op.create_index('ix_service_tickets_order_id',        'service_tickets', ['order_id'])
    op.create_index('ix_service_tickets_amc_contract_id', 'service_tickets', ['amc_contract_id'])
    op.create_index('ix_service_tickets_service_type',    'service_tickets', ['service_type'])
    op.create_index('ix_service_tickets_status',          'service_tickets', ['status'])


def downgrade():
    op.drop_index('ix_service_tickets_status',          table_name='service_tickets')
    op.drop_index('ix_service_tickets_service_type',    table_name='service_tickets')
    op.drop_index('ix_service_tickets_amc_contract_id', table_name='service_tickets')
    op.drop_index('ix_service_tickets_order_id',        table_name='service_tickets')
    op.drop_index('ix_service_tickets_tenant_id',       table_name='service_tickets')
    op.drop_table('service_tickets')

    op.drop_index('ix_amc_contracts_status',    table_name='amc_contracts')
    op.drop_index('ix_amc_contracts_order_id',  table_name='amc_contracts')
    op.drop_index('ix_amc_contracts_tenant_id', table_name='amc_contracts')
    op.drop_table('amc_contracts')

    op.drop_index('ix_warranties_status',    table_name='warranties')
    op.drop_index('ix_warranties_order_id',  table_name='warranties')
    op.drop_index('ix_warranties_tenant_id', table_name='warranties')
    op.drop_table('warranties')
