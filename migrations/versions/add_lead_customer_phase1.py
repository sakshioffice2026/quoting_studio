"""Add customers, leads, interactions tables (Phase 1 — Lead & Customer).

Revision ID: add_lead_customer_phase1
Revises: add_profile_compatible_shapes
Create Date: 2026-09-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_lead_customer_phase1'
down_revision = 'add_profile_compatible_shapes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_customers_tenant_id', 'customers', ['tenant_id'])
    op.create_index('ix_customers_phone', 'customers', ['phone'])
    op.create_index('ix_customers_email', 'customers', ['email'])
    op.create_index('ix_customers_tenant_phone', 'customers', ['tenant_id', 'phone'])
    op.create_index('ix_customers_tenant_email', 'customers', ['tenant_id', 'email'])

    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('source_channel', sa.String(length=30), nullable=False, server_default='website'),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('project_city', sa.String(length=120), nullable=True),
        sa.Column('project_address', sa.String(length=500), nullable=True),
        sa.Column('product_interest', sa.String(length=20), nullable=True),
        sa.Column('approx_quantity', sa.Integer(), nullable=True),
        sa.Column('budget_band', sa.String(length=60), nullable=True),
        sa.Column('assigned_to', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='LEAD-NEW'),
        sa.Column('follow_up_status', sa.String(length=20), nullable=True),
        sa.Column('duplicate_of_lead_id', sa.Integer(), sa.ForeignKey('leads.id'), nullable=True),
        sa.Column('lost_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_leads_tenant_id', 'leads', ['tenant_id'])
    op.create_index('ix_leads_customer_id', 'leads', ['customer_id'])
    op.create_index('ix_leads_project_id', 'leads', ['project_id'])
    op.create_index('ix_leads_phone', 'leads', ['phone'])
    op.create_index('ix_leads_email', 'leads', ['email'])
    op.create_index('ix_leads_assigned_to', 'leads', ['assigned_to'])
    op.create_index('ix_leads_status', 'leads', ['status'])
    op.create_index('ix_leads_follow_up_status', 'leads', ['follow_up_status'])

    op.create_table(
        'interactions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('interaction_type', sa.String(length=20), nullable=False),
        sa.Column('outcome', sa.String(length=30), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('next_action_date', sa.Date(), nullable=True),
        sa.Column('qualification_score', sa.String(length=10), nullable=True),
        sa.Column('lost_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_interactions_tenant_id', 'interactions', ['tenant_id'])
    op.create_index('ix_interactions_lead_id', 'interactions', ['lead_id'])


def downgrade():
    op.drop_index('ix_interactions_lead_id', table_name='interactions')
    op.drop_index('ix_interactions_tenant_id', table_name='interactions')
    op.drop_table('interactions')

    op.drop_index('ix_leads_follow_up_status', table_name='leads')
    op.drop_index('ix_leads_status', table_name='leads')
    op.drop_index('ix_leads_assigned_to', table_name='leads')
    op.drop_index('ix_leads_email', table_name='leads')
    op.drop_index('ix_leads_phone', table_name='leads')
    op.drop_index('ix_leads_project_id', table_name='leads')
    op.drop_index('ix_leads_customer_id', table_name='leads')
    op.drop_index('ix_leads_tenant_id', table_name='leads')
    op.drop_table('leads')

    op.drop_index('ix_customers_tenant_email', table_name='customers')
    op.drop_index('ix_customers_tenant_phone', table_name='customers')
    op.drop_index('ix_customers_email', table_name='customers')
    op.drop_index('ix_customers_phone', table_name='customers')
    op.drop_index('ix_customers_tenant_id', table_name='customers')
    op.drop_table('customers')
