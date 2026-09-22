"""Add site_type + project_type_ids to template_responses (multi-category support)
and create template_uploads table (site photo / floor plan uploads).

Revision ID: add_multi_category_and_uploads
Revises: req_templates_p12
Create Date: 2026-09-22 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'add_multi_category_and_uploads'
down_revision = 'req_templates_p12'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(table_name, index_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade():
    with op.batch_alter_table('template_responses') as batch_op:
        if not _column_exists('template_responses', 'site_type'):
            batch_op.add_column(sa.Column('site_type', sa.String(30), nullable=True))
        if not _column_exists('template_responses', 'project_type_ids'):
            batch_op.add_column(sa.Column('project_type_ids', sa.JSON(), nullable=True))
        batch_op.alter_column('project_type_id', existing_type=sa.Integer(), nullable=True)

    if not _table_exists('template_uploads'):
        op.create_table(
            'template_uploads',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('response_id', sa.Integer(), sa.ForeignKey('template_responses.id', ondelete='CASCADE'), nullable=False),
            sa.Column('stored_filename', sa.String(255), nullable=False),
            sa.Column('original_filename', sa.String(255), nullable=False),
            sa.Column('content_type', sa.String(100), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('uploaded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not _index_exists('template_uploads', 'idx_template_uploads_response'):
        op.create_index('idx_template_uploads_response', 'template_uploads', ['response_id'])

    if not _index_exists('template_uploads', 'idx_template_uploads_tenant'):
        op.create_index('idx_template_uploads_tenant', 'template_uploads', ['tenant_id'])


def downgrade():
    if _index_exists('template_uploads', 'idx_template_uploads_tenant'):
        op.drop_index('idx_template_uploads_tenant', table_name='template_uploads')

    if _index_exists('template_uploads', 'idx_template_uploads_response'):
        op.drop_index('idx_template_uploads_response', table_name='template_uploads')

    if _table_exists('template_uploads'):
        op.drop_table('template_uploads')

    with op.batch_alter_table('template_responses') as batch_op:
        batch_op.alter_column('project_type_id', existing_type=sa.Integer(), nullable=False)
        if _column_exists('template_responses', 'project_type_ids'):
            batch_op.drop_column('project_type_ids')
        if _column_exists('template_responses', 'site_type'):
            batch_op.drop_column('site_type')
