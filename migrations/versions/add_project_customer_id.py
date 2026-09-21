"""Add customer_id to projects (link project to the registered customer).

Revision ID: add_project_customer_id
Revises: add_project_name
Create Date: 2026-09-21 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision      = 'add_project_customer_id'
down_revision = 'add_project_name'
branch_labels = None
depends_on    = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _fks(table):
    return {f['name'] for f in sa.inspect(op.get_bind()).get_foreign_keys(table)}


def upgrade():
    if 'customer_id' not in _columns('projects'):
        op.add_column(
            'projects',
            sa.Column('customer_id', sa.Integer(), nullable=True),
        )

    if 'fk_projects_customer_id' not in _fks('projects'):
        op.create_foreign_key(
            'fk_projects_customer_id', 'projects', 'customers',
            ['customer_id'], ['id'],
        )

    if 'ix_projects_customer_id' not in _indexes('projects'):
        op.create_index('ix_projects_customer_id', 'projects', ['customer_id'])

    # Backfill: projects created from a lead take that lead's customer.
    op.execute(
        "UPDATE projects p "
        "JOIN leads l ON l.project_id = p.id "
        "SET p.customer_id = l.customer_id "
        "WHERE p.id > 0 AND p.customer_id IS NULL AND l.customer_id IS NOT NULL"
    )


def downgrade():
    if 'fk_projects_customer_id' in _fks('projects'):
        op.drop_constraint('fk_projects_customer_id', 'projects', type_='foreignkey')
    if 'ix_projects_customer_id' in _indexes('projects'):
        op.drop_index('ix_projects_customer_id', table_name='projects')
    if 'customer_id' in _columns('projects'):
        op.drop_column('projects', 'customer_id')
