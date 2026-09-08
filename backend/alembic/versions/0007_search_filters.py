"""topic search cache: user-editable filters (date range, region, subs)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Trend Analysis tab now exposes date range, min-subscriber
    # threshold, and region as editable filters (previously fixed by env
    # var). date_from/date_to are the actual gating filters going forward;
    # lookback_days becomes a derived, display-only convenience and
    # region_code can now be genuinely unset ("Global" — no regionCode
    # sent to YouTube at all), so both must accept NULL.
    op.add_column('topic_search_cache', sa.Column('date_from', sa.Date(), nullable=True))
    op.add_column('topic_search_cache', sa.Column('date_to', sa.Date(), nullable=True))
    op.alter_column('topic_search_cache', 'lookback_days', existing_type=sa.Integer(), nullable=True)
    op.alter_column(
        'topic_search_cache', 'region_code',
        existing_type=sa.String(length=8), type_=sa.String(length=16), nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'topic_search_cache', 'region_code',
        existing_type=sa.String(length=16), type_=sa.String(length=8), nullable=False,
    )
    op.alter_column('topic_search_cache', 'lookback_days', existing_type=sa.Integer(), nullable=False)
    op.drop_column('topic_search_cache', 'date_to')
    op.drop_column('topic_search_cache', 'date_from')
