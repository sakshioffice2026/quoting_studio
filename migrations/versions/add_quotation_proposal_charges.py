"""Add installation/transport/AMC/warranty charge fields to quotations.

Revision ID: add_quotation_proposal_charges
Revises: add_multi_category_and_uploads
Create Date: 2026-09-22 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_quotation_proposal_charges'
down_revision = 'add_multi_category_and_uploads'
branch_labels = None
depends_on    = None


def upgrade():
    op.add_column('quotations', sa.Column('installation_charge', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('quotations', sa.Column('transport_charge',    sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('quotations', sa.Column('other_charges_json',  sa.Text(), nullable=True))

    op.add_column('quotations', sa.Column('amc_offered',    sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('quotations', sa.Column('amc_offer_tier', sa.String(20), nullable=True))
    op.add_column('quotations', sa.Column('amc_price',      sa.Numeric(12, 2), nullable=True))

    op.add_column('quotations', sa.Column('warranty_months',     sa.Integer(), nullable=True, server_default='12'))
    op.add_column('quotations', sa.Column('warranty_terms_text', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('quotations', 'warranty_terms_text')
    op.drop_column('quotations', 'warranty_months')

    op.drop_column('quotations', 'amc_price')
    op.drop_column('quotations', 'amc_offer_tier')
    op.drop_column('quotations', 'amc_offered')

    op.drop_column('quotations', 'other_charges_json')
    op.drop_column('quotations', 'transport_charge')
    op.drop_column('quotations', 'installation_charge')
