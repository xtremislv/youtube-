"""median baseline

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('videos', sa.Column('median_views_baseline', sa.Float(), nullable=True))
    op.add_column('videos', sa.Column('overperform_ratio_median', sa.Float(), nullable=True))
    op.create_index(
        op.f('ix_videos_overperform_ratio_median'), 'videos', ['overperform_ratio_median'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_videos_overperform_ratio_median'), table_name='videos')
    op.drop_column('videos', 'overperform_ratio_median')
    op.drop_column('videos', 'median_views_baseline')
