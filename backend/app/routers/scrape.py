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
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import require_scrape_api_key, settings_dep
from app.models import ScrapeRun
from app.schemas import ScrapeRunOut, ScrapeTriggerResponse
from app.scrape_service import run_daily_scrape

router = APIRouter(prefix="/api/scrape", tags=["scrape"])


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
        elapsed_seconds = (dt.datetime.utcnow() - last_run.started_at).total_seconds()
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
