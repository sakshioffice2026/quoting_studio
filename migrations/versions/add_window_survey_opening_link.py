"""Add windows.survey_opening_id — links a Window/door unit back to the
surveyed opening it was created from (Phase 3 gap closure / Phase 4 wiring).

Revision ID: add_window_survey_opening_link
Revises: add_design_approval_phase4
Create Date: 2026-09-19 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_window_survey_opening_link'
down_revision = 'add_design_approval_phase4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('windows', sa.Column('survey_opening_id', sa.Integer(),
                                        sa.ForeignKey('survey_openings.id'), nullable=True))
    op.create_index('ix_windows_survey_opening_id', 'windows', ['survey_opening_id'])


def downgrade():
    op.drop_index('ix_windows_survey_opening_id', table_name='windows')
    op.drop_column('windows', 'survey_opening_id')
