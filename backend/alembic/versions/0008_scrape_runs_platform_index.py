"""scrape_runs: composite (platform, started_at) index

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24 00:00:00.000000
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backs the manual-scrape cooldown check (app/routers/scrape.py's
    # trigger_manual_scrape) and GET /api/system/status's "last scrape"
    # lookup, both of which filter scrape_runs by platform and then order by
    # started_at desc — this index lets that be a single index scan instead
    # of a full-table scan + sort as this log table grows. The existing
    # single-column ix_scrape_runs_started_at index is left in place; it
    # still backs GET /api/scrape/runs's platform-agnostic listing.
    op.create_index(
        'ix_scrape_runs_platform_started_at',
        'scrape_runs',
        ['platform', 'started_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_scrape_runs_platform_started_at', table_name='scrape_runs')
