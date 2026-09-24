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
from app.db_lock import LOCK_KEY_TOPIC_SEARCH, session_scoped_lock
from app.deps import settings_dep
from app.error_safety import safe_error_message
from app.models import ScrapeRun, TopicSearchCache
from app.quota import get_quota_used_today
from app.schemas import TopicSearchChannelResult, TopicSearchRequest, TopicSearchResult
from app.timeutil import ensure_aware_utc, utcnow
from app.topic_search import TopicSearchOutcome, estimate_quota_cost, get_cached_search

router = APIRouter(prefix="/api/search", tags=["search"])
logger = logging.getLogger(__name__)


def _resolve_filters(payload: TopicSearchRequest, settings: Settings) -> tuple[int, str | None, dt.date | None, dt.date | None]:
    """Validates and resolves the Trend Analysis tab's editable filters
    (min-subscriber gate, date range, region) against Settings' defaults
    for whatever the request omits. Raises HTTPException(400) on anything
    malformed rather than letting a bad request reach YouTube. Returns
    (min_subscribers, region_code, date_from, date_to) — region_code and
    the dates may be None (meaning "no restriction"), min_subscribers
    never is.
    """
    min_subscribers = payload.min_subscribers if payload.min_subscribers is not None else settings.search_min_subscribers
    if min_subscribers < 0:
        raise HTTPException(status_code=400, detail="min_subscribers must not be negative.")

    region = (payload.region or "").strip().upper()
    if not region:
        region_code: str | None = settings.search_region_code
    elif region == "GLOBAL":
        region_code = None
    else:
        region_code = region

    def _parse_date(raw: str | None, field_name: str) -> dt.date | None:
        if not raw:
            return None
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{field_name} must be a valid YYYY-MM-DD date.") from None

    date_from = _parse_date(payload.date_from, "date_from")
    date_to = _parse_date(payload.date_to, "date_to")

    # Neither end supplied at all (as opposed to an explicit "" from the
    # UI's "All time" preset) — a bare API request with no date fields
    # gets the old fixed-lookback behavior rather than an unbounded (and
    # much more expensive/lower-quality) all-time search by accident.
    if payload.date_from is None and payload.date_to is None:
        date_from = utcnow().date() - dt.timedelta(days=settings.search_lookback_days)

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must not be after date_to.")

    return min_subscribers, region_code, date_from, date_to


def _to_response(outcome: TopicSearchOutcome) -> TopicSearchResult:
    return TopicSearchResult(
        query=outcome.query,
        searched_at=outcome.searched_at,
        date_from=outcome.date_from.isoformat() if outcome.date_from else None,
        date_to=outcome.date_to.isoformat() if outcome.date_to else None,
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

    min_subscribers, region_code, date_from, date_to = _resolve_filters(payload, settings)

    # Closes the check-then-act race between the cooldown check below and
    # the cache row that actually records a search happened — see
    # app/db_lock.py's docstring. Unlike /api/scrape/run-manual's lock, this
    # one has to be session-scoped (survive the several db.commit() calls
    # below) rather than released at the first commit: the cooldown here is
    # keyed off TopicSearchCache.searched_at, which isn't written until
    # run_topic_search's whole YouTube round trip finishes — a plain
    # transaction-scoped lock would release right after the early
    # ScrapeRun("running") commit, long before that write, and so wouldn't
    # actually stop two concurrent requests from both passing the cooldown
    # check. Held on its own dedicated connection (not `db`) specifically
    # because this section commits `db` multiple times — see
    # session_scoped_lock's docstring for why taking it on `db` itself would
    # be unsafe. A no-op on the SQLite the test suite runs against.
    with session_scoped_lock(db, LOCK_KEY_TOPIC_SEARCH):
        # Cooldown — keyed off the cache's own searched_at rather than a
        # separate lookup, since there's always exactly zero or one row there.
        cache = db.get(TopicSearchCache, 1)
        if cache is not None:
            searched_at = ensure_aware_utc(cache.searched_at)
            now = utcnow()
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

        run = ScrapeRun(platform="youtube_search", started_at=utcnow(), status="running")
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
            outcome = run_topic_search(
                db,
                settings,
                query,
                min_subscribers=min_subscribers,
                region_code=region_code,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as exc:  # noqa: BLE001 — one YouTube API hiccup (network error,
            # quota exceeded mid-flight) covers the whole search; roll back so a
            # partially-flushed cache write can't leave the single-slot cache
            # half-overwritten, log it, and surface a clean 502 rather than a
            # bare stack trace — matches /api/scrape/check-velocity's handling.
            db.rollback()
            run.status = "failed"
            run.finished_at = utcnow()
            # safe_error_message, not str(exc): this endpoint has no API key, so
            # whoever sent the request that caused this reads `detail` directly
            # — google-api-python-client's HttpError embeds the full failing
            # request URL (key=YOUTUBE_API_KEY included) in str(exc), which must
            # never reach an unauthenticated caller. See app/error_safety.py.
            safe_message = safe_error_message(exc)
            run.error_message = safe_message[:4000]
            db.commit()
            logger.exception("Topic search failed for query=%r", query)
            raise HTTPException(status_code=502, detail=f"Topic search failed: {safe_message}") from exc

        run.status = "success"
        run.finished_at = utcnow()
        run.youtube_quota_units_used = outcome.youtube_quota_units_used
        db.commit()

        return _to_response(outcome)
