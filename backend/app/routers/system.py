"""
/api/system/status — one call the frontend uses to fill in the sidebar's
"API Quota" widget, the "Overperformance" nav badge count, and the
workspace name — all of which were hardcoded placeholders (84%, 14,
"Consumer Tech Competitors") in the original Figma mock.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import settings_dep
from app.models import Channel, ScrapeRun, Video
from app.schemas import SystemStatus

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=SystemStatus)
def get_status(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)) -> SystemStatus:
    today_start = dt.datetime.combine(dt.date.today(), dt.time.min)
    quota_used_today = (
        db.query(func.coalesce(func.sum(ScrapeRun.youtube_quota_units_used), 0))
        .filter(ScrapeRun.platform == "youtube", ScrapeRun.started_at >= today_start)
        .scalar()
        or 0
    )

    last_run = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).first()

    total_channels = db.query(func.count(Channel.id)).filter(Channel.is_active.is_(True)).scalar() or 0
    total_videos = db.query(func.count(Video.id)).scalar() or 0
    overperform_count = (
        db.query(func.count(Video.id))
        .filter(Video.overperform_ratio.is_not(None), Video.overperform_ratio >= settings.overperform_ratio_default)
        .scalar()
        or 0
    )

    budget = settings.youtube_daily_quota_budget
    pct = round(min(quota_used_today / budget, 1.0) * 100, 1) if budget else 0.0

    return SystemStatus(
        workspace_name=settings.workspace_name,
        youtube_quota_used_today=int(quota_used_today),
        youtube_quota_budget=budget,
        youtube_quota_pct=pct,
        last_scrape_started_at=last_run.started_at if last_run else None,
        last_scrape_status=last_run.status if last_run else None,
        total_channels=total_channels,
        total_videos=total_videos,
        overperform_count=overperform_count,
    )
