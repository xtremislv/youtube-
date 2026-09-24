"""
/api/channels — the "Competitor Roster": add, list, tag, and remove the
YouTube channels / Instagram profiles this workspace tracks.

Adding a channel here does **not** immediately scrape its videos (an
Instagram actor run can take a minute or more — too slow for a request/
response cycle, and doing it synchronously would make "add 10 competitors"
painfully slow). It registers the channel and — for YouTube only, since one
``channels.list`` call costs a single quota unit and is fast — resolves its
real display name/avatar/subscriber count right away so the roster doesn't
sit blank. The next scrape run (scheduled, or a manual POST
/api/scrape/run) is what populates its videos.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.channel_service import DuplicateChannelError, InvalidPlatformError, add_channel
from app.config import Settings
from app.database import get_db
from app.deps import settings_dep
from app.formatting import format_count
from app.models import Channel, Video
from app.schemas import ChannelCreate, ChannelOut, ChannelUpdate, CohortOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channels", tags=["channels"])

PLATFORMS = {"all", "youtube", "instagram"}


def _median_views_last_10_by_channel(db: Session) -> dict[str, float]:
    """One channel -> median `views` of that channel's 10 most recently
    published videos (platform-agnostic — works the same for a YouTube
    channel or an Instagram profile, since it only looks at published_at
    and views). Backs the channel card's "Median (last 10)" stat.

    The "last 10 rows per group" half of this is pushed into SQL via a
    ROW_NUMBER() window (supported identically by the Postgres this runs
    against in prod and the SQLite the test suite uses, both new enough to
    have it) so this only ever pulls at most 10 rows per channel back to
    Python, instead of every video row in the whole table — this used to
    run an unfiltered `Video.channel_id, Video.views, Video.published_at`
    query with no LIMIT at all, on every GET /api/channels, so its cost grew
    with the *entire* videos table regardless of how many channels or
    videos-per-channel actually mattered for the answer.

    The median itself stays a Python `statistics.median` call rather than
    also pushing it into SQL: a median needs `percentile_cont`, whose
    behavior/support differs between Postgres and SQLite, and by this point
    there are at most 10 rows per channel to run it over, so doing it in
    Python is both simpler and no longer a meaningful cost.
    """
    row_number = func.row_number().over(partition_by=Video.channel_id, order_by=Video.published_at.desc())
    ranked = db.query(Video.channel_id.label("channel_id"), Video.views.label("views"), row_number.label("rn")).subquery()
    rows = db.query(ranked.c.channel_id, ranked.c.views).filter(ranked.c.rn <= 10).all()
    by_channel: dict[str, list[int]] = defaultdict(list)
    for channel_id, views in rows:
        by_channel[channel_id].append(views)
    return {channel_id: statistics.median(views_list) for channel_id, views_list in by_channel.items() if views_list}


def _to_out(
    channel: Channel,
    avg_views: float | None = None,
    video_count: int = 0,
    last_published_at: dt.date | None = None,
    median_views_last_10: float | None = None,
) -> ChannelOut:
    return ChannelOut(
        id=channel.id,
        name=channel.name,
        platform=channel.platform,
        avatar_initials=channel.avatar_initials,
        avatar_url=channel.avatar_url,
        subs=format_count(channel.subscriber_count),
        subscriber_count=channel.subscriber_count,
        handle=channel.handle,
        cohort=channel.cohort,
        is_active=channel.is_active,
        avg_views=round(avg_views) if avg_views is not None else None,
        median_views_last_10=round(median_views_last_10) if median_views_last_10 is not None else None,
        video_count=video_count or 0,
        last_published_at=last_published_at.isoformat() if last_published_at else None,
    )


@router.get("", response_model=list[ChannelOut])
def list_channels(
    platform: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> list[ChannelOut]:
    if platform is not None and platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail=f"platform must be one of {sorted(PLATFORMS)}.")

    # One grouped query for every channel's video stats (avg views, video
    # count, most recent publish date), outer-joined onto the channel list —
    # avoids an N+1 query per channel. Backs the roster's channel card;
    # channels with no scraped videos yet just get None/0 from the outer join.
    stats_subq = (
        db.query(
            Video.channel_id.label("channel_id"),
            func.avg(Video.views).label("avg_views"),
            func.count(Video.id).label("video_count"),
            func.max(Video.published_at).label("last_published_at"),
        )
        .group_by(Video.channel_id)
        .subquery()
    )

    query = db.query(Channel, stats_subq.c.avg_views, stats_subq.c.video_count, stats_subq.c.last_published_at).outerjoin(
        stats_subq, stats_subq.c.channel_id == Channel.id
    )
    if platform and platform != "all":
        query = query.filter(Channel.platform == platform)
    if not include_inactive:
        query = query.filter(Channel.is_active.is_(True))
    rows = query.order_by(Channel.name).all()
    median_last_10 = _median_views_last_10_by_channel(db)
    return [
        _to_out(
            channel,
            avg_views=avg_views,
            video_count=video_count,
            last_published_at=last_published_at,
            median_views_last_10=median_last_10.get(channel.id),
        )
        for channel, avg_views, video_count, last_published_at in rows
    ]


@router.get("/cohorts", response_model=list[CohortOut])
def list_cohorts(db: Session = Depends(get_db)) -> list[CohortOut]:
    """Backs the sidebar's "Saved Cohorts" list — real counts, grouped by the
    optional `cohort` tag set when a channel was added (or later via PATCH)."""
    rows = (
        db.query(Channel.cohort, func.count(Channel.id))
        .filter(Channel.cohort.is_not(None), Channel.is_active.is_(True))
        .group_by(Channel.cohort)
        .order_by(Channel.cohort)
        .all()
    )
    return [CohortOut(label=label, count=count) for label, count in rows]


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)) -> ChannelOut:
    try:
        channel = add_channel(db, settings, payload)
    except InvalidPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateChannelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # No user auth in front of this endpoint (see PRODUCTION_ROADMAP.md's
    # Phase 2 notes), so there's no "who" to log — but "what changed and
    # when" is still worth a record for debugging a roster that changed
    # unexpectedly, matching the audit-trail style already used for scrape
    # runs (app/scrape_service.py) and settings changes below.
    logger.info("Channel added: %s (%s)", channel.id, channel.handle)
    return _to_out(channel)


@router.patch("/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: str, payload: ChannelUpdate, db: Session = Depends(get_db)) -> ChannelOut:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if payload.cohort is not None:
        channel.cohort = payload.cohort or None
    if payload.is_active is not None:
        channel.is_active = payload.is_active
    if payload.notes is not None:
        channel.notes = payload.notes
    db.commit()
    db.refresh(channel)
    logger.info(
        "Channel updated: %s (cohort=%r, isActive=%s)", channel.id, channel.cohort, channel.is_active
    )
    return _to_out(channel)


@router.delete("/{channel_id}", status_code=204, response_model=None)
def delete_channel(channel_id: str, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    handle = channel.handle  # captured before commit — a deleted+committed
    # ORM instance's attributes are expired and can't be safely re-read from
    # a row that no longer exists.
    db.delete(channel)
    db.commit()
    logger.info("Channel removed: %s (%s)", channel_id, handle)
