"""
/api/settings — small runtime, dashboard-toggleable switches. Distinct from
app/config.py's Settings (env vars, fixed at deploy time): these live in the
DB and take effect immediately, no redeploy needed.

Currently just one: pausing Instagram (Apify) scraping, to control Apify
usage/cost. The sidebar's "Apify Usage" toggle calls this. What actually
enforces it is app/scrape_service.py's run_daily_scrape — the one function
POST /api/scrape/run (the GitHub Actions schedule), POST
/api/scrape/run-manual (the dashboard's "Refresh data" button), and the
in-process scheduler all funnel through — so this one switch covers every
way a scrape can be triggered, not just the dashboard.

No auth on these routes: they don't spend quota or credit themselves (only
*reading* a flag that a scrape checks later does), and the dashboard has no
user auth yet to hang a permission check off of — see
PRODUCTION_ROADMAP.md's Phase 2 notes on adding real authentication before
this app is exposed beyond a trusted team.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import WorkspaceSettingsOut, WorkspaceSettingsUpdate
from app.settings_service import get_workspace_settings, set_instagram_scraping_enabled

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/scraper", response_model=WorkspaceSettingsOut)
def get_scraper_settings(db: Session = Depends(get_db)) -> WorkspaceSettingsOut:
    return WorkspaceSettingsOut.model_validate(get_workspace_settings(db))


@router.patch("/scraper", response_model=WorkspaceSettingsOut)
def update_scraper_settings(payload: WorkspaceSettingsUpdate, db: Session = Depends(get_db)) -> WorkspaceSettingsOut:
    row = set_instagram_scraping_enabled(db, payload.instagram_scraping_enabled)
    return WorkspaceSettingsOut.model_validate(row)
