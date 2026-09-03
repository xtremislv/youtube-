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

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.channel_service import DuplicateChannelError, InvalidPlatformError, add_channel
from app.config import Settings
from app.database import get_db
from app.deps import settings_dep
from app.formatting import format_count
from app.models import Channel
from app.schemas import ChannelCreate, ChannelOut, ChannelUpdate, CohortOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channels", tags=["channels"])


def _to_out(channel: Channel) -> ChannelOut:
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
    )


@router.get("", response_model=list[ChannelOut])
def list_channels(
    platform: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> list[ChannelOut]:
    query = db.query(Channel)
    if platform and platform != "all":
        query = query.filter(Channel.platform == platform)
    if not include_inactive:
        query = query.filter(Channel.is_active.is_(True))
    channels = query.order_by(Channel.name).all()
    return [_to_out(c) for c in channels]


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
    return _to_out(channel)


@router.delete("/{channel_id}", status_code=204, response_model=None)
def delete_channel(channel_id: str, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(channel)
    db.commit()
