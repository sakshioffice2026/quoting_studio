"""Add quotations table (Phase 5 — Quotation / Presentation).

Revision ID: add_quotation_phase5
Revises: add_design_approval_sent_expired
Create Date: 2026-09-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_quotation_phase5'
down_revision = 'add_design_approval_sent_expired'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'quotations',
        sa.Column('id',                   sa.Integer(),     primary_key=True),
        sa.Column('tenant_id',            sa.Integer(),     sa.ForeignKey('tenants.id'),          nullable=False),
        sa.Column('project_id',           sa.Integer(),     sa.ForeignKey('projects.id'),         nullable=False),
        sa.Column('design_approval_id',   sa.Integer(),     sa.ForeignKey('design_approvals.id'), nullable=True),
        sa.Column('quotation_number',     sa.String(40),    unique=True, nullable=False),
        sa.Column('quotation_version',    sa.Integer(),     nullable=False, server_default='1'),
        sa.Column('parent_quotation_id',  sa.Integer(),     sa.ForeignKey('quotations.id'),       nullable=True),
        sa.Column('status',               sa.String(40),    nullable=False, server_default='QUOTE-DRAFT'),
        sa.Column('line_items_json',      sa.Text(),        nullable=True),
        sa.Column('subtotal',             sa.Numeric(12,2), nullable=True),
        sa.Column('discount_pct',         sa.Numeric(5,2),  nullable=True,  server_default='0'),
        sa.Column('discount_amount',      sa.Numeric(12,2), nullable=True,  server_default='0'),
        sa.Column('discount_approved_by', sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('discount_approved_at', sa.DateTime(),    nullable=True),
        sa.Column('tax_rate',             sa.Numeric(5,4),  nullable=False, server_default='0.2000'),
        sa.Column('tax_amount',           sa.Numeric(12,2), nullable=True),
        sa.Column('grand_total',          sa.Numeric(12,2), nullable=True),
        sa.Column('payment_terms_template', sa.String(100), nullable=True),
        sa.Column('validity_days',        sa.Integer(),     nullable=False, server_default='30'),
        sa.Column('validity_date',        sa.Date(),        nullable=True),
        sa.Column('prepared_by',          sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('sent_by',              sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('sent_at',              sa.DateTime(),    nullable=True),
        sa.Column('accepted_by_name',     sa.String(200),   nullable=True),
        sa.Column('accepted_at',          sa.DateTime(),    nullable=True),
        sa.Column('acceptance_method',    sa.String(50),    nullable=True),
        sa.Column('lost_at',              sa.DateTime(),    nullable=True),
        sa.Column('lost_reason',          sa.Text(),        nullable=True),
        sa.Column('negotiation_notes',    sa.Text(),        nullable=True),
        sa.Column('pdf_path',             sa.String(500),   nullable=True),
        sa.Column('created_at',           sa.DateTime(),    nullable=False),
        sa.Column('updated_at',           sa.DateTime(),    nullable=False),
    )
    op.create_index('ix_quotations_tenant_id',          'quotations', ['tenant_id'])
    op.create_index('ix_quotations_project_id',         'quotations', ['project_id'])
    op.create_index('ix_quotations_design_approval_id', 'quotations', ['design_approval_id'])
    op.create_index('ix_quotations_status',             'quotations', ['status'])
    op.create_index('ix_quotations_parent_quotation_id','quotations', ['parent_quotation_id'])


def downgrade():
    op.drop_index('ix_quotations_parent_quotation_id', table_name='quotations')
    op.drop_index('ix_quotations_status',              table_name='quotations')
    op.drop_index('ix_quotations_design_approval_id',  table_name='quotations')
    op.drop_index('ix_quotations_project_id',          table_name='quotations')
    op.drop_index('ix_quotations_tenant_id',           table_name='quotations')
    op.drop_table('quotations')
