"""Add site_type + project_type_ids to template_responses (multi-category support)
and create template_uploads table (site photo / floor plan uploads).

Revision ID: add_multi_category_and_uploads
Revises: add_requirement_templates_phase12
Create Date: 2026-09-22 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_multi_category_and_uploads'
down_revision = 'add_requirement_templates_phase12'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('template_responses') as batch_op:
        batch_op.add_column(sa.Column('site_type', sa.String(30), nullable=True))
        batch_op.add_column(sa.Column('project_type_ids', sa.JSON(), nullable=True))
        batch_op.alter_column('project_type_id', existing_type=sa.Integer(), nullable=True)

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
    op.create_index('idx_template_uploads_response', 'template_uploads', ['response_id'])
    op.create_index('idx_template_uploads_tenant', 'template_uploads', ['tenant_id'])


def downgrade():
    op.drop_index('idx_template_uploads_tenant', table_name='template_uploads')
    op.drop_index('idx_template_uploads_response', table_name='template_uploads')
    op.drop_table('template_uploads')

    with op.batch_alter_table('template_responses') as batch_op:
        batch_op.alter_column('project_type_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('project_type_ids')
        batch_op.drop_column('site_type')
