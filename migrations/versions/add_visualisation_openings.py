"""Add openings_json to visualisations (multiple openings per photo).

Revision ID: add_visualisation_openings
Revises: add_quotation_proposal_charges
Create Date: 2026-09-29 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_visualisation_openings'
down_revision = 'add_quotation_proposal_charges'
branch_labels = None
depends_on    = None


def upgrade():
    op.add_column('visualisations',
                  sa.Column('openings_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('visualisations', 'openings_json')
