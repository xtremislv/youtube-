"""
/api/videos — powers the main dashboard grid.

Every query parameter here maps 1:1 to a control in the frontend's
``FilterBar`` (src/App.tsx's ``Filters`` interface): platform toggle,
multi-channel select, date range, an optional "min views" threshold, format,
and sort order. Filtering and sorting happen in SQL rather than in the
browser (the original Figma mock filtered a hardcoded 12-video array
client-side; once channels/history grow past a few thousand rows that
stops being reasonable, so this endpoint does the work database-side and
the frontend just re-fetches when a filter changes).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, or_
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.database import get_db
from app.deps import settings_dep
from app.formatting import format_duration
from app.models import Video
from app.schemas import VideoListResponse, VideoOut

router = APIRouter(prefix="/api/videos", tags=["videos"])

SORT_COLUMNS = {"ratio", "views", "date", "engagement"}


def _to_out(video: Video) -> VideoOut:
    return VideoOut(
        id=video.id,
        channel_id=video.channel_id,
        channel_name=video.channel.name,
        platform=video.platform,
        title=video.title,
        thumbnail=video.thumbnail_url,
        url=video.external_url,
        views=video.views,
        avg_views=video.avg_views_baseline,
        median_views=video.median_views_baseline,
        likes=video.likes,
        comments=video.comments,
        published_at=video.published_at.isoformat(),
        duration=format_duration(video.duration_seconds),
        format=video.format,
        overperform_ratio=video.overperform_ratio,
        overperform_ratio_median=video.overperform_ratio_median,
        has_sponsor_segment=video.has_sponsor_segment,
        sponsor_segment_seconds=video.sponsor_segment_seconds,
        h1_views=video.h1_views,
        h1_ratio=video.h1_ratio,
        h3_views=video.h3_views,
        h3_ratio=video.h3_ratio,
        h6_views=video.h6_views,
        h6_ratio=video.h6_ratio,
    )


@router.get("", response_model=VideoListResponse)
def list_videos(
    platform: str = Query("all"),
    channels: list[str] | None = Query(default=None, description="Repeat for multiple, e.g. ?channels=a&channels=b"),
    date_from: date | None = None,
    date_to: date | None = None,
    views_threshold: int | None = Query(default=None, ge=0),
    format: str = Query("all", description="'all' | 'long' | 'short' | 'reel'"),
    sort_by: str = Query("ratio", description="'ratio' | 'views' | 'date' | 'engagement'"),
    metric: str = Query(
        "average",
        description=(
            "'average' | 'median' — which trailing baseline drives sort_by='ratio' and the returned "
            "overperformCount. Both avgViews/overperformRatio and medianViews/overperformRatioMedian are "
            "always included on every video regardless of this, so the frontend can toggle instantly."
        ),
    ),
    overperform_ratio_threshold: float | None = Query(
        default=None, description="Overrides OVERPERFORM_RATIO_DEFAULT for the returned overperformCount only."
    ),
    has_sponsor: bool | None = Query(
        default=None,
        description=(
            "Filter by SponsorBlock-detected sponsor/campaign segments (see app/sponsorblock.py) — "
            "true = only videos with one; false = only videos SponsorBlock has actually been checked for "
            "and confirmed clean (not yet checked doesn't count as 'confirmed clean'). YouTube-only: an "
            "Instagram video is never flagged, since there's no equivalent data source for it."
        ),
    ),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> VideoListResponse:
    threshold = overperform_ratio_threshold if overperform_ratio_threshold is not None else settings.overperform_ratio_default
    ratio_column = Video.overperform_ratio_median if metric == "median" else Video.overperform_ratio

    query = db.query(Video).options(joinedload(Video.channel))

    if platform != "all":
        query = query.filter(Video.platform == platform)
    if channels:
        query = query.filter(Video.channel_id.in_(channels))
    if date_from:
        query = query.filter(Video.published_at >= date_from)
    if date_to:
        query = query.filter(Video.published_at <= date_to)
    if views_threshold is not None:
        query = query.filter(Video.views >= views_threshold)
    if format != "all":
        if format == "short":
            query = query.filter(or_(Video.format == "short", Video.format == "reel"))
        else:
            query = query.filter(Video.format == format)
    if has_sponsor is True:
        query = query.filter(Video.has_sponsor_segment.is_(True))
    elif has_sponsor is False:
        query = query.filter(Video.sponsor_checked_at.is_not(None), Video.has_sponsor_segment.is_(False))

    total = query.count()
    overperform_count = query.filter(ratio_column.is_not(None), ratio_column >= threshold).count()

    if sort_by not in SORT_COLUMNS:
        sort_by = "ratio"
    if sort_by == "views":
        query = query.order_by(Video.views.desc())
    elif sort_by == "date":
        query = query.order_by(Video.published_at.desc())
    elif sort_by == "engagement":
        engagement = case((Video.likes.is_not(None), Video.likes), else_=0) + case(
            (Video.comments.is_not(None), Video.comments), else_=0
        )
        query = query.order_by(engagement.desc())
    else:  # ratio — NULLs (not enough history yet) sort last, not first
        query = query.order_by(ratio_column.is_(None), ratio_column.desc())

    rows = query.offset(offset).limit(limit).all()

    return VideoListResponse(
        videos=[_to_out(v) for v in rows],
        total=total,
        overperform_count=overperform_count,
    )
