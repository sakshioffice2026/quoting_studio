"""Add shape column to windows table.

Revision ID: add_shape_column
Revises: 
Create Date: 2026-08-22 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_shape_column'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('windows', sa.Column('shape', sa.String(50), nullable=False, server_default='rectangular'))


def downgrade():
    op.drop_column('windows', 'shape')
