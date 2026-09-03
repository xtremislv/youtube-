"""
Optional in-process daily scheduler, for deployments where the API process
itself stays running around the clock (Docker Compose on a VPS, a Render
*paid* always-on service, a plain systemd service). Guarded by
``ENABLE_INTERNAL_SCHEDULER`` — leave it off on anything that scales to
zero or sleeps when idle (Render's free web service, most serverless
hosts), since APScheduler simply won't fire while the process is asleep.
For those hosts, use the GitHub Actions cron workflow
(.github/workflows/daily-scrape.yml) to hit POST /api/scrape/run instead —
see backend/README.md.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.database import SessionLocal
from app.scrape_service import run_daily_scrape

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job(settings: Settings) -> None:
    db = SessionLocal()
    try:
        logger.info("Internal scheduler: starting daily scrape")
        runs = run_daily_scrape(db, settings)
        for run in runs:
            logger.info(
                "Scrape run finished: platform=%s status=%s channels=%s videos=%s quota=%s",
                run.platform,
                run.status,
                run.channels_processed,
                run.videos_upserted,
                run.youtube_quota_units_used,
            )
    finally:
        db.close()


def start_scheduler(settings: Settings) -> BackgroundScheduler | None:
    global _scheduler
    if not settings.enable_internal_scheduler:
        logger.info("Internal scheduler disabled (ENABLE_INTERNAL_SCHEDULER=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _job,
        CronTrigger(hour=settings.daily_scrape_hour, minute=settings.daily_scrape_minute),
        args=[settings],
        id="daily-scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "Internal scheduler started: daily scrape at %02d:%02d server time",
        settings.daily_scrape_hour,
        settings.daily_scrape_minute,
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
