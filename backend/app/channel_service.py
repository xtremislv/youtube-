"""
Shared "add a channel to track" logic, used by both POST /api/channels (see
app/routers/channels.py) and scripts/seed_channels.py (bulk-loading a
channel list from a JSON file) — kept out of the router so the CLI script
doesn't need to spin up FastAPI/HTTP just to reuse this code.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.formatting import initials_from_name, normalize_handle
from app.models import Channel
from app.schemas import ChannelCreate
from app.scrapers.youtube import YouTubeClient, parse_channel_resource, resolve_channel_input

logger = logging.getLogger(__name__)


class DuplicateChannelError(Exception):
    pass


class InvalidPlatformError(Exception):
    pass


def add_channel(db: Session, settings: Settings, payload: ChannelCreate) -> Channel:
    platform = payload.platform.strip().lower()
    if platform not in ("youtube", "instagram"):
        raise InvalidPlatformError("platform must be 'youtube' or 'instagram'")

    if platform == "youtube":
        channel = _build_youtube_channel(db, settings, payload)
    else:
        channel = _build_instagram_channel(db, payload)

    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def _build_youtube_channel(db: Session, settings: Settings, payload: ChannelCreate) -> Channel:
    channel_id, handle = resolve_channel_input(payload.handle)
    external_id = channel_id or f"@{handle}"
    db_id = f"youtube:{external_id}"
    if db.get(Channel, db_id):
        raise DuplicateChannelError(f"{db_id} is already tracked")

    channel = Channel(
        id=db_id,
        platform="youtube",
        external_id=external_id,
        handle=handle or external_id,
        name=handle or external_id,
        avatar_initials=initials_from_name(handle or external_id),
        cohort=payload.cohort,
    )

    # Best-effort synchronous identity resolution (cheap: 1 quota unit). If
    # it fails (bad key, channel truly doesn't exist, network hiccup) the
    # row is still created — the next scrape run retries it and surfaces
    # the error there instead of blocking channel creation.
    if settings.youtube_api_key:
        try:
            client = YouTubeClient(settings.youtube_api_key)
            raw = client.get_channel(channel_id=channel_id, handle=handle)
            if raw:
                parsed = parse_channel_resource(raw)
                resolved_id = f"youtube:{parsed['external_id']}"
                if resolved_id != db_id and db.get(Channel, resolved_id):
                    raise DuplicateChannelError(f"{resolved_id} is already tracked")
                channel.id = resolved_id
                channel.external_id = parsed["external_id"]
                channel.name = parsed["name"]
                channel.avatar_url = parsed["avatar_url"]
                channel.avatar_initials = parsed["avatar_initials"]
                channel.subscriber_count = parsed["subscriber_count"]
        except DuplicateChannelError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Could not resolve YouTube channel identity for %s at creation time", payload.handle)

    return channel


def _build_instagram_channel(db: Session, payload: ChannelCreate) -> Channel:
    username = normalize_handle(payload.handle, "instagram")
    db_id = f"instagram:{username}"
    if db.get(Channel, db_id):
        raise DuplicateChannelError(f"{db_id} is already tracked")
    return Channel(
        id=db_id,
        platform="instagram",
        external_id=username,
        handle=username,
        name=username,
        avatar_initials=initials_from_name(username),
        cohort=payload.cohort,
    )
