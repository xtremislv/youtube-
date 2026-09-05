"""
/api/scrape — manually kick off, or check on, the scrape job that normally
runs on a daily schedule (see app/scheduler.py and .github/workflows/
daily-scrape.yml).

Two ways to trigger a run, with two different guards:

- ``POST /run`` is behind an API key (see app/deps.py) since it spends real
  YouTube quota / Apify credit — this is what the GitHub Actions workflow
  and any manual curl call use.
- ``POST /run-manual`` has no API key. It's what the dashboard's own
  "Refresh now" button calls directly from the browser, which has nowhere
  secret to keep an API key — anything shipped in the frontend's JS bundle
  is visible to anyone who opens dev tools on the deployed site. Instead of
  a secret, it's guarded by a cooldown (``MANUAL_SCRAPE_COOLDOWN_SECONDS``):
  it refuses to start a new scrape if the most recent one of the requested
  platform (or any platform, if none given) started too recently. That caps
  how much quota/credit repeated clicks — or someone spamming a shared
  dashboard link — could burn, without needing real user auth in front of
  it. See PRODUCTION_ROADMAP.md's Phase 2 notes on adding real
  authentication before this app is exposed beyond a trusted team.
- ``POST /check-velocity`` is the early-velocity (h1/h3/h6) job's trigger —
  see app/velocity.py. Behind the same API key as ``/run`` since it also
  spends real YouTube quota, just on its own much-more-frequent (hourly)
  schedule (.github/workflows/hourly-velocity-check.yml) rather than the
  main scrape's ~6x/day one — a checkpoint at 1/3/6 hours needs roughly
  hourly checks around the clock to land inside its grace window, which the
  daytime-only main scrape cadence can't reliably provide.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import require_scrape_api_key, settings_dep
from app.models import ScrapeRun
from app.schemas import ScrapeRunOut, ScrapeTriggerResponse, VelocityCheckResponse
from app.scrape_service import run_daily_scrape

router = APIRouter(prefix="/api/scrape", tags=["scrape"])
logger = logging.getLogger(__name__)


@router.post("/run", response_model=ScrapeTriggerResponse, dependencies=[Depends(require_scrape_api_key)])
def trigger_scrape(
    platform: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> ScrapeTriggerResponse:
    runs = run_daily_scrape(db, settings, platform=platform)
    return ScrapeTriggerResponse(
        message=f"Ran {len(runs)} platform scrape(s).",
        runs=[ScrapeRunOut.model_validate(r) for r in runs],
    )


@router.post("/run-manual", response_model=ScrapeTriggerResponse)
def trigger_manual_scrape(
    platform: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> ScrapeTriggerResponse:
    if platform not in (None, "youtube", "instagram"):
        raise HTTPException(status_code=400, detail="platform must be 'youtube' or 'instagram' if given.")

    query = db.query(ScrapeRun)
    if platform is not None:
        query = query.filter(ScrapeRun.platform == platform)
    last_run = query.order_by(ScrapeRun.started_at.desc()).first()

    if last_run is not None:
        # Postgres columns are DateTime(timezone=True), so a real deploy
        # reads started_at back as timezone-aware — but the sqlite used by
        # the test suite always hands back naive datetimes regardless of
        # column type, and older rows may predate this fix either way.
        # Coerce to aware-UTC on both sides so the subtraction never raises
        # "can't subtract offset-naive and offset-aware datetimes".
        started_at = last_run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        elapsed_seconds = (now - started_at).total_seconds()
        remaining_seconds = settings.manual_scrape_cooldown_seconds - elapsed_seconds
        if remaining_seconds > 0:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"A scrape already ran {int(elapsed_seconds)}s ago. "
                    f"Try again in {int(remaining_seconds)}s."
                ),
                headers={"Retry-After": str(int(remaining_seconds))},
            )

    runs = run_daily_scrape(db, settings, platform=platform)
    return ScrapeTriggerResponse(
        message=f"Ran {len(runs)} platform scrape(s).",
        runs=[ScrapeRunOut.model_validate(r) for r in runs],
    )


@router.get("/runs", response_model=list[ScrapeRunOut])
def list_runs(limit: int = 20, db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    rows = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit).all()
    return [ScrapeRunOut.model_validate(r) for r in rows]


@router.post("/check-velocity", response_model=VelocityCheckResponse, dependencies=[Depends(require_scrape_api_key)])
def trigger_velocity_check(
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> VelocityCheckResponse:
    from app.velocity import capture_velocity_snapshots

    if not settings.youtube_api_key:
        raise HTTPException(status_code=503, detail="YOUTUBE_API_KEY is not configured.")

    try:
        stats = capture_velocity_snapshots(db, settings)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — unlike /run (per-channel try/except,
        # always 200 with a per-run status), this endpoint has no equivalent
        # audit trail (see app/velocity.py's docstring on that Phase-1
        # limitation) or per-video isolation — a single YouTube API hiccup
        # (network error, quota exceeded) covers the whole batch. Roll back
        # so a mid-batch failure can't leave a partially-flushed transaction
        # committed, log it, and surface a clear 502 rather than a bare
        # stack trace — the hourly cadence means a missed run just retries
        # next hour (curl --fail already causes the GitHub Actions step to
        # retry — see hourly-velocity-check.yml).
        db.rollback()
        logger.exception("Velocity checkpoint check failed")
        raise HTTPException(status_code=502, detail=f"Velocity check failed: {exc}") from exc

    return VelocityCheckResponse(
        message=(
            f"Checked {stats.videos_checked} video(s), captured "
            f"{stats.checkpoints_captured} checkpoint(s) across "
            f"{stats.channels_recomputed} channel(s)."
        ),
        videos_checked=stats.videos_checked,
        checkpoints_captured=stats.checkpoints_captured,
        channels_recomputed=stats.channels_recomputed,
    )
