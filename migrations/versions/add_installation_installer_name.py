"""Add installer_name to installations.

Revision ID: add_installation_installer_name
Revises: add_unit_gating_phase13
Create Date: 2026-09-29 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'add_installation_installer_name'
down_revision = 'add_unit_gating_phase13'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'installations',
        sa.Column(
            'installer_name',
            sa.String(length=200),
            nullable=True
        )
    )


def downgrade():
    op.drop_column('installations', 'installer_name')