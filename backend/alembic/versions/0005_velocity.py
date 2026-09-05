"""velocity tracking

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-05 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('videos', sa.Column('published_at_ts', sa.DateTime(timezone=True), nullable=True))
    op.add_column('videos', sa.Column('h1_views', sa.Integer(), nullable=True))
    op.add_column('videos', sa.Column('h1_ratio', sa.Float(), nullable=True))
    op.add_column('videos', sa.Column('h3_views', sa.Integer(), nullable=True))
    op.add_column('videos', sa.Column('h3_ratio', sa.Float(), nullable=True))
    op.add_column('videos', sa.Column('h6_views', sa.Integer(), nullable=True))
    op.add_column('videos', sa.Column('h6_ratio', sa.Float(), nullable=True))
    op.add_column('videos', sa.Column('velocity_checked_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'video_velocity_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('video_id', sa.String(), sa.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('checkpoint_hours', sa.Integer(), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False),
        sa.Column('likes', sa.Integer(), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hours_since_publish', sa.Float(), nullable=False),
    )
    op.create_index(
        op.f('ix_velocity_snapshots_video_checkpoint'),
        'video_velocity_snapshots',
        ['video_id', 'checkpoint_hours'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_velocity_snapshots_video_checkpoint'), table_name='video_velocity_snapshots')
    op.drop_table('video_velocity_snapshots')
    op.drop_column('videos', 'velocity_checked_at')
    op.drop_column('videos', 'h6_ratio')
    op.drop_column('videos', 'h6_views')
    op.drop_column('videos', 'h3_ratio')
    op.drop_column('videos', 'h3_views')
    op.drop_column('videos', 'h1_ratio')
    op.drop_column('videos', 'h1_views')
    op.drop_column('videos', 'published_at_ts')
