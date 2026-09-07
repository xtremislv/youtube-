"""topic search cache

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-07 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'topic_search_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query', sa.String(length=200), nullable=False),
        sa.Column('searched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lookback_days', sa.Integer(), nullable=False),
        sa.Column('min_subscribers', sa.Integer(), nullable=False),
        sa.Column('region_code', sa.String(length=8), nullable=False),
        sa.Column('top_n', sa.Integer(), nullable=False),
        sa.Column('total_candidates', sa.Integer(), nullable=False),
        sa.Column('outperform_count', sa.Integer(), nullable=False),
        sa.Column('youtube_quota_units_used', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'topic_search_cache_channels',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('channel_external_id', sa.String(), nullable=False),
        sa.Column('channel_name', sa.String(), nullable=False),
        sa.Column('channel_handle', sa.String(), nullable=True),
        sa.Column('channel_avatar_url', sa.String(), nullable=True),
        sa.Column('subscriber_count', sa.Integer(), nullable=False),
        sa.Column('video_external_id', sa.String(), nullable=False),
        sa.Column('video_title', sa.String(), nullable=False),
        sa.Column('video_thumbnail_url', sa.String(), nullable=True),
        sa.Column('video_url', sa.String(), nullable=False),
        sa.Column('video_views', sa.Integer(), nullable=False),
        sa.Column('video_published_at', sa.Date(), nullable=False),
        sa.Column('rank_score', sa.Float(), nullable=False),
        sa.Column('channel_median_views', sa.Float(), nullable=True),
        sa.Column('overperform_ratio', sa.Float(), nullable=True),
        sa.Column('is_outperforming', sa.Boolean(), nullable=False),
    )
    op.create_index(
        op.f('ix_topic_search_cache_channels_rank'),
        'topic_search_cache_channels',
        ['rank'],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_topic_search_cache_channels_rank'), table_name='topic_search_cache_channels')
    op.drop_table('topic_search_cache_channels')
    op.drop_table('topic_search_cache')
