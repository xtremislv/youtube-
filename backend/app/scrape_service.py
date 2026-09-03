"""
Orchestrates "scrape everything that's due" — the one function that the
HTTP trigger (routers/scrape.py), the CLI script (scripts/run_scrape.py),
and the in-process scheduler (app/scheduler.py) all call. Keeping it in one
place means there's exactly one code path to test and reason about,
regardless of what fired it.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Channel, ScrapeRun

logger = logging.getLogger(__name__)


def run_daily_scrape(db: Session, settings: Settings, *, platform: str | None = None) -> list[ScrapeRun]:
    """
    Scrapes every active channel, one ScrapeRun row per platform attempted.
    ``platform`` restricts to just "youtube" or "instagram" (used by the
    GitHub Actions workflow to run them as separate jobs/steps so a slow
    Instagram batch doesn't delay fresh YouTube numbers, and so a missing
    Apify token doesn't block YouTube scraping or vice versa).
    """
    runs: list[ScrapeRun] = []
    if platform in (None, "youtube"):
        runs.append(_scrape_platform(db, settings, "youtube"))
    if platform in (None, "instagram"):
        runs.append(_scrape_platform(db, settings, "instagram"))
    return runs


def _scrape_platform(db: Session, settings: Settings, platform: str) -> ScrapeRun:
    run = ScrapeRun(platform=platform, status="running", started_at=dt.datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    channels = db.query(Channel).filter(Channel.platform == platform, Channel.is_active.is_(True)).all()

    if not channels:
        run.status = "success"
        run.finished_at = dt.datetime.utcnow()
        db.commit()
        return run

    errors: list[str] = []
    try:
        if platform == "youtube":
            _run_youtube(db, settings, channels, run, errors)
        else:
            _run_instagram(db, settings, channels, run, errors)
    except Exception as exc:  # noqa: BLE001 — record and surface, never crash the caller
        logger.exception("Scrape run failed for platform=%s", platform)
        errors.append(str(exc))

    run.finished_at = dt.datetime.utcnow()
    run.status = "failed" if not run.channels_processed else ("partial" if errors else "success")
    run.error_message = "; ".join(errors)[:4000] if errors else None
    db.commit()
    db.refresh(run)
    return run


def _run_youtube(db: Session, settings: Settings, channels: list[Channel], run: ScrapeRun, errors: list[str]) -> None:
    from app.scrapers.youtube import YouTubeClient, scrape_channel

    if not settings.youtube_api_key:
        errors.append("YOUTUBE_API_KEY is not configured.")
        return

    client = YouTubeClient(settings.youtube_api_key)
    for channel in channels:
        try:
            stats = scrape_channel(client, db, channel, settings=settings)
            run.videos_upserted += stats.videos_upserted
            run.channels_processed += 1
            errors.extend(stats.errors)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("YouTube scrape failed for channel %s", channel.id)
            errors.append(f"{channel.id}: {exc}")
    run.youtube_quota_units_used = client.quota_units_used


def _run_instagram(db: Session, settings: Settings, channels: list[Channel], run: ScrapeRun, errors: list[str]) -> None:
    from app.scrapers.instagram import ApifyInstagramClient, scrape_channel

    if not settings.apify_api_token:
        errors.append("APIFY_API_TOKEN is not configured.")
        return

    client = ApifyInstagramClient(settings.apify_api_token, settings.apify_instagram_actor_id)
    for channel in channels:
        try:
            stats = scrape_channel(client, db, channel, settings=settings)
            run.videos_upserted += stats.videos_upserted
            run.channels_processed += 1
            errors.extend(stats.errors)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("Instagram scrape failed for channel %s", channel.id)
            errors.append(f"{channel.id}: {exc}")
    run.apify_runs_started = client.runs_started
