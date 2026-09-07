"""
Shared "how much YouTube quota has been spent today" accounting — used by
both GET /api/system/status (the sidebar's "API Quota" widget) and the
topic search guardrail (app/routers/search.py), so the two can never
silently disagree about what's already been spent today.

Quota-spending platforms recorded on ScrapeRun: "youtube" (the tracked-
channel scraper, app/scrapers/youtube.py) and "youtube_search" (a
user-triggered topic search, app/topic_search.py) — kept as a distinct
platform value specifically so a topic search is never picked up by the
"last scrape status" queries in app/routers/system.py, which only care
about "youtube"/"instagram".
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ScrapeRun

QUOTA_SPENDING_PLATFORMS = ("youtube", "youtube_search")


def get_quota_used_today(db: Session) -> int:
    today_start = dt.datetime.combine(dt.date.today(), dt.time.min)
    return (
        db.query(func.coalesce(func.sum(ScrapeRun.youtube_quota_units_used), 0))
        .filter(ScrapeRun.platform.in_(QUOTA_SPENDING_PLATFORMS), ScrapeRun.started_at >= today_start)
        .scalar()
        or 0
    )
