"""Add project_name to leads and projects.

Revision ID: add_project_name
Revises: add_amc_phase11
Create Date: 2026-09-21 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_project_name'
down_revision = 'add_amc_phase11'
branch_labels = None
depends_on    = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    # Idempotent: safe to run even if the columns were added manually.
    if 'project_name' not in _columns('leads'):
        op.add_column(
            'leads',
            sa.Column('project_name', sa.String(200), nullable=True),
        )

    if 'project_name' not in _columns('projects'):
        op.add_column(
            'projects',
            sa.Column('project_name', sa.String(200), nullable=True),
        )

    if 'ix_projects_project_name' not in _indexes('projects'):
        op.create_index('ix_projects_project_name', 'projects', ['project_name'])

    # Backfill existing rows so they are recognisable in lists/search.
    op.execute(
        "UPDATE projects SET project_name = customer_name "
        "WHERE id > 0 AND (project_name IS NULL OR project_name = '')"
    )
    op.execute(
        "UPDATE leads SET project_name = customer_name "
        "WHERE id > 0 AND (project_name IS NULL OR project_name = '')"
    )


def downgrade():
    if 'ix_projects_project_name' in _indexes('projects'):
        op.drop_index('ix_projects_project_name', table_name='projects')
    if 'project_name' in _columns('projects'):
        op.drop_column('projects', 'project_name')
    if 'project_name' in _columns('leads'):
        op.drop_column('leads', 'project_name')
