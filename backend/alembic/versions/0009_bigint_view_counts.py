"""widen view-count columns to BigInteger

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25 00:00:00.000000

videos.views, video_velocity_snapshots.views, and
topic_search_cache_channels.video_views all store the same underlying
quantity — a YouTube video's view count — as a 32-bit Integer, which tops
out at ~2.1 billion. Real videos have passed that (e.g. "Baby Shark Dance"
is well past 15 billion), so a tracked channel's video reaching that count
would hit an overflow error (or silently wrap, depending on the codec/
column type) on the next scrape write, rather than just... having a large
number.

This is a safe widening (INTEGER -> BIGINT): every existing value already
fits in a BIGINT, so there's no truncation risk, and Postgres performs this
specific ALTER COLUMN TYPE as a fast metadata-only change when the new type
is a strict superset of the old one's range (no table rewrite needed) — see
the Postgres release notes for ALTER TABLE ... ALTER COLUMN TYPE bigint.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("videos", "views", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
    op.alter_column(
        "video_velocity_snapshots", "views", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False
    )
    op.alter_column(
        "topic_search_cache_channels",
        "video_views",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Only safe if no existing row actually exceeds Integer's range — true
    # today, but a downgrade run after this has been live for a while
    # should double check that first.
    op.alter_column(
        "topic_search_cache_channels",
        "video_views",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "video_velocity_snapshots", "views", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False
    )
    op.alter_column("videos", "views", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)
