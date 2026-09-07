"""
/api/search — the "is this topic trending" feature (see app/topic_search.py
for the full method, and its module docstring for the single-slot caching
design). Two endpoints:

- ``POST /topic`` runs a fresh search against YouTube right now — real
  quota spend, cooldown- and budget-guarded — overwrites the single-slot
  cache, and returns it.
- ``GET /latest`` returns the current cache (or ``null`` if no search has
  ever run) without touching YouTube at all — the page-reload path, so
  reopening the Search tab doesn't re-spend quota just to show what you
  last searched.

Both have no API key, same reasoning as ``/api/scrape/run-manual``: this is
called directly from the browser, which has nowhere secret to keep one.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import settings_dep
from app.models import ScrapeRun, TopicSearchCache
from app.quota import get_quota_used_today
from app.schemas import TopicSearchChannelResult, TopicSearchRequest, TopicSearchResult
from app.topic_search import TopicSearchOutcome, estimate_quota_cost, get_cached_search

router = APIRouter(prefix="/api/search", tags=["search"])
logger = logging.getLogger(__name__)


def _to_response(outcome: TopicSearchOutcome) -> TopicSearchResult:
    return TopicSearchResult(
        query=outcome.query,
        searched_at=outcome.searched_at,
        lookback_days=outcome.lookback_days,
        min_subscribers=outcome.min_subscribers,
        region_code=outcome.region_code,
        top_n=outcome.top_n,
        total_candidates=outcome.total_candidates,
        outperform_count=outcome.outperform_count,
        youtube_quota_units_used=outcome.youtube_quota_units_used,
        channels=[
            TopicSearchChannelResult(
                rank=r.rank,
                channel_id=r.candidate.channel_external_id,
                channel_name=r.candidate.channel_name,
                channel_handle=r.candidate.channel_handle,
                channel_avatar_url=r.candidate.channel_avatar_url,
                subscriber_count=r.candidate.subscriber_count,
                video_id=r.candidate.video_external_id,
                video_title=r.candidate.title,
                video_thumbnail_url=r.candidate.thumbnail_url,
                video_url=r.candidate.video_url,
                video_views=r.candidate.views,
                video_published_at=r.candidate.published_at.isoformat(),
                score=r.score,
                channel_median_views=r.channel_median_views,
                overperform_ratio=r.overperform_ratio,
                is_outperforming=r.is_outperforming,
            )
            for r in outcome.channels
        ],
    )


@router.get("/latest", response_model=TopicSearchResult | None)
def get_latest(db: Session = Depends(get_db)) -> TopicSearchResult | None:
    outcome = get_cached_search(db)
    return _to_response(outcome) if outcome else None


@router.post("/topic", response_model=TopicSearchResult)
def search_topic(
    payload: TopicSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TopicSearchResult:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty.")
    if not settings.youtube_api_key:
        raise HTTPException(status_code=503, detail="YOUTUBE_API_KEY is not configured.")

    # Cooldown — keyed off the cache's own searched_at rather than a
    # separate lookup, since there's always exactly zero or one row there.
    cache = db.get(TopicSearchCache, 1)
    if cache is not None:
        searched_at = cache.searched_at
        if searched_at.tzinfo is None:
            searched_at = searched_at.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        elapsed_seconds = (now - searched_at).total_seconds()
        remaining_seconds = settings.topic_search_cooldown_seconds - elapsed_seconds
        if remaining_seconds > 0:
            raise HTTPException(
                status_code=429,
                detail=f"A search already ran {int(elapsed_seconds)}s ago. Try again in {int(remaining_seconds)}s.",
                headers={"Retry-After": str(int(remaining_seconds))},
            )

    # Budget guard — refuse up front rather than fail halfway through after
    # already spending most of a day's remaining quota on a search that
    # then can't finish its (cheaper) per-channel median lookups.
    estimated_cost = estimate_quota_cost(settings)
    used_today = get_quota_used_today(db)
    if used_today + estimated_cost > settings.youtube_daily_quota_budget:
        remaining = max(0, settings.youtube_daily_quota_budget - used_today)
        raise HTTPException(
            status_code=429,
            detail=(
                f"This search could cost up to ~{estimated_cost} quota units, but only ~{remaining} "
                "remain in today's budget. Try again after the daily quota resets."
            ),
        )

    run = ScrapeRun(platform="youtube_search", started_at=dt.datetime.utcnow(), status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    # Local import (matches /api/scrape/check-velocity's pattern in
    # app/routers/scrape.py): the one call in this endpoint that actually
    # talks to YouTube, imported lazily so tests can monkeypatch
    # app.routers.search.run_topic_search without needing the real
    # YOUTUBE_API_KEY / network access this would otherwise require.
    from app.topic_search import run_topic_search

    try:
        outcome = run_topic_search(db, settings, query)
    except Exception as exc:  # noqa: BLE001 — one YouTube API hiccup (network error,
        # quota exceeded mid-flight) covers the whole search; roll back so a
        # partially-flushed cache write can't leave the single-slot cache
        # half-overwritten, log it, and surface a clean 502 rather than a
        # bare stack trace — matches /api/scrape/check-velocity's handling.
        db.rollback()
        run.status = "failed"
        run.finished_at = dt.datetime.utcnow()
        run.error_message = str(exc)[:4000]
        db.commit()
        logger.exception("Topic search failed for query=%r", query)
        raise HTTPException(status_code=502, detail=f"Topic search failed: {exc}") from exc

    run.status = "success"
    run.finished_at = dt.datetime.utcnow()
    run.youtube_quota_units_used = outcome.youtube_quota_units_used
    db.commit()

    return _to_response(outcome)
