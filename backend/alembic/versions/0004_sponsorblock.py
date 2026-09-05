"""sponsorblock

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'videos',
        sa.Column('has_sponsor_segment', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('videos', sa.Column('sponsor_segment_seconds', sa.Float(), nullable=True))
    op.add_column('videos', sa.Column('sponsor_checked_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f('ix_videos_has_sponsor_segment'), 'videos', ['has_sponsor_segment'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_videos_has_sponsor_segment'), table_name='videos')
    op.drop_column('videos', 'sponsor_checked_at')
    op.drop_column('videos', 'sponsor_segment_seconds')
    op.drop_column('videos', 'has_sponsor_segment')
