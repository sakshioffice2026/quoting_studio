"""Add compatible_shapes column to cad_profiles table.

Revision ID: add_profile_compatible_shapes
Revises: add_shape_column
Create Date: 2026-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_profile_compatible_shapes'
down_revision = 'add_shape_column'
branch_labels = None
depends_on = None


def upgrade():
    # JSON array of shape strings, e.g. '["rectangle","arched"]'.
    # NULL/empty = compatible with every shape (existing rows keep showing
    # everywhere until someone opts in to a restriction).
    op.add_column('cad_profiles',
                   sa.Column('compatible_shapes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('cad_profiles', 'compatible_shapes')
