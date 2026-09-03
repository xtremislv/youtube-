"""
/api/scrape — manually kick off, or check on, the scrape job that normally
runs on a daily schedule (see app/scheduler.py and .github/workflows/
daily-scrape.yml). POST is behind an API key (see app/deps.py) since it
spends real YouTube quota / Apify credit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
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


@router.get("/runs", response_model=list[ScrapeRunOut])
def list_runs(limit: int = 20, db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    rows = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit).all()
    return [ScrapeRunOut.model_validate(r) for r in rows]
