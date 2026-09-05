"""
YouTube Data API v3 scraper.

Split deliberately into two layers so the important part is testable
without hitting the network or spending API quota:

- ``YouTubeClient`` — the only thing in this file that talks to Google.
  Thin, and tracks how many quota units it has spent (``quota_units_used``)
  so a scrape run can report real numbers to the "API Quota" widget.
- The ``parse_*`` functions — pure functions that turn one raw API JSON
  object into the normalized dict shape the rest of the app expects.
  ``tests/test_youtube_parsing.py`` feeds these real (recorded) API response
  shapes and checks the output, with no network involved.
- ``scrape_channel`` — orchestrates the two: discover the channel, discover
  new video ids, refresh stats for every tracked video (new *and* old, since
  view counts keep climbing), upsert into the DB, recompute overperformance
  baselines for the whole channel.

Quota budgeting (see backend/README.md for the full breakdown): this scraper
never calls ``search.list`` (100 units) — it walks each channel's "uploads"
playlist instead (``playlistItems.list`` = 1 unit/page of up to 50 videos)
and refreshes stats for already-tracked videos via ``videos.list`` batched
50-at-a-time (1 unit per 50 videos, regardless of how many parts you ask
for). At the free 10,000 units/day budget that comfortably covers dozens of
channels scraped daily.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.formatting import initials_from_name, normalize_handle
from app.models import Channel, ScrapeRun, Video
from app.overperformance import recompute_and_store_channel_baselines
from app.scrapers.duration import classify_youtube_format, parse_iso8601_duration

logger = logging.getLogger(__name__)

PLAYLIST_ITEMS_PAGE_SIZE = 50
VIDEOS_BATCH_SIZE = 50
# How many pages of a channel's uploads playlist to walk on the very first
# scrape of a channel (each page = 1 quota unit). Subsequent daily runs only
# need 1 page (page 1 always has the newest uploads first) unless a channel
# posts more than 50 videos/day.
BACKFILL_PAGES = 4


class YouTubeClient:
    """Thin wrapper around the official googleapiclient YouTube resource."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is not set — see backend/.env.example")
        self._youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        self.quota_units_used = 0

    # -- raw calls, each annotated with its documented quota cost ------------

    def get_channel(self, *, channel_id: str | None = None, handle: str | None = None) -> dict | None:
        """channels.list — 1 unit."""
        kwargs: dict = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            kwargs["id"] = channel_id
        elif handle:
            kwargs["forHandle"] = handle if handle.startswith("@") else f"@{handle}"
        else:
            raise ValueError("Must supply channel_id or handle")
        resp = self._youtube.channels().list(**kwargs).execute()
        self.quota_units_used += 1
        items = resp.get("items", [])
        return items[0] if items else None

    def list_uploads_video_ids(self, uploads_playlist_id: str, *, max_pages: int) -> list[str]:
        """playlistItems.list — 1 unit per page (up to 50 items/page)."""
        video_ids: list[str] = []
        page_token: str | None = None
        pages_fetched = 0
        while pages_fetched < max_pages:
            resp = (
                self._youtube.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=PLAYLIST_ITEMS_PAGE_SIZE,
                    pageToken=page_token,
                )
                .execute()
            )
            self.quota_units_used += 1
            pages_fetched += 1
            video_ids.extend(item["contentDetails"]["videoId"] for item in resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return video_ids

    def get_videos(self, video_ids: list[str]) -> list[dict]:
        """videos.list, batched 50 ids/call — 1 unit per call."""
        results: list[dict] = []
        for i in range(0, len(video_ids), VIDEOS_BATCH_SIZE):
            batch = video_ids[i : i + VIDEOS_BATCH_SIZE]
            resp = (
                self._youtube.videos()
                .list(part="snippet,statistics,contentDetails", id=",".join(batch))
                .execute()
            )
            self.quota_units_used += 1
            results.extend(resp.get("items", []))
        return results


# ── Pure parsing (no network, fully unit-testable) ──────────────────────────


def parse_channel_resource(raw: dict) -> dict:
    """Normalize a raw ``channels.list`` item."""
    snippet = raw.get("snippet", {})
    stats = raw.get("statistics", {})
    content = raw.get("contentDetails", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
    return {
        "external_id": raw["id"],
        "name": snippet.get("title", raw["id"]),
        "avatar_url": thumb.get("url"),
        "avatar_initials": initials_from_name(snippet.get("title", "")),
        "subscriber_count": (
            None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0) or 0)
        ),
        "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads"),
    }


def parse_video_resource(raw: dict, *, channel_id: str) -> dict:
    """Normalize a raw ``videos.list`` item into the app's Video shape."""
    snippet = raw.get("snippet", {})
    stats = raw.get("statistics", {})
    content = raw.get("contentDetails", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}

    duration_seconds = parse_iso8601_duration(content.get("duration", ""))
    published_at = dt.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")).date()

    return {
        "id": f"youtube:{raw['id']}",
        "channel_id": channel_id,
        "platform": "youtube",
        "title": snippet.get("title", "(untitled)"),
        "thumbnail_url": thumb.get("url"),
        "external_url": f"https://www.youtube.com/watch?v={raw['id']}",
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
        "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
        "published_at": published_at,
        "duration_seconds": duration_seconds,
        "format": classify_youtube_format(duration_seconds),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


@dataclass
class ChannelScrapeStats:
    videos_upserted: int = 0
    quota_units_used: int = 0
    sponsor_checks_made: int = 0
    errors: list[str] = field(default_factory=list)


def resolve_channel_input(handle_or_url_or_id: str) -> tuple[str | None, str | None]:
    """
    Best-effort split of user input into (channel_id, handle). Accepts a raw
    channel ID (starts with 'UC'), a '@handle', a bare handle, or a full
    youtube.com/@handle or /channel/UC... URL.
    Returns (channel_id, handle) — exactly one will be non-None.
    """
    value = handle_or_url_or_id.strip()
    if "youtube.com" in value:
        value = value.rstrip("/").split("/")[-1]
    if value.startswith("UC") and len(value) == 24 and "@" not in value:
        return value, None
    return None, normalize_handle(value, "youtube")


def scrape_channel(
    client: YouTubeClient,
    db: Session,
    channel: Channel,
    *,
    settings,
    sponsor_budget: "SponsorCheckBudget | None" = None,
) -> ChannelScrapeStats:
    """
    Refresh one already-tracked channel: discover new uploads, refresh view
    counts for the whole tracked history, upsert, recompute baselines, then
    (if enabled) check newest-first for SponsorBlock segments.

    ``sponsor_budget`` is normally shared across every channel in one
    platform-wide scrape run (see app/scrape_service.py) so a single
    channel's backlog can't eat the whole run's SponsorBlock allowance;
    passing None (e.g. a standalone/test call) gives this channel its own
    fresh budget sized from settings instead.
    """
    stats = ChannelScrapeStats()

    channel_id = None if channel.external_id.startswith("@") else channel.external_id
    handle = channel.external_id if channel.external_id.startswith("@") else None
    raw_channel = client.get_channel(channel_id=channel_id, handle=handle)
    if raw_channel is None:
        stats.errors.append(f"YouTube channel not found: {channel.external_id}")
        return stats
    parsed = parse_channel_resource(raw_channel)

    channel.external_id = parsed["external_id"]
    channel.name = parsed["name"]
    channel.avatar_url = parsed["avatar_url"]
    channel.avatar_initials = parsed["avatar_initials"]
    channel.subscriber_count = parsed["subscriber_count"]

    uploads_playlist_id = parsed["uploads_playlist_id"]
    is_first_scrape = db.query(Video).filter(Video.channel_id == channel.id).count() == 0
    max_pages = BACKFILL_PAGES if is_first_scrape else 1

    discovered_ids = client.list_uploads_video_ids(uploads_playlist_id, max_pages=max_pages) if uploads_playlist_id else []

    already_tracked_ids = [
        row[0].removeprefix("youtube:")
        for row in db.query(Video.id).filter(Video.channel_id == channel.id).all()
    ]
    all_ids = list(dict.fromkeys(already_tracked_ids + discovered_ids))  # de-duped, order-preserving

    raw_videos = client.get_videos(all_ids) if all_ids else []
    for raw_video in raw_videos:
        parsed_video = parse_video_resource(raw_video, channel_id=channel.id)
        existing = db.get(Video, parsed_video["id"])
        if existing is None:
            db.add(Video(**parsed_video))
        else:
            for key, value in parsed_video.items():
                setattr(existing, key, value)
        stats.videos_upserted += 1

    db.flush()
    recompute_and_store_channel_baselines(db, channel.id, settings)

    if settings.sponsorblock_enabled:
        from app.sponsorblock import SponsorCheckBudget, check_and_store_sponsor_segments

        budget = sponsor_budget if sponsor_budget is not None else SponsorCheckBudget(settings.sponsorblock_max_checks_per_scrape)
        # Newest-first: a limited budget should prioritize this channel's
        # most recent uploads (what a competitor-tracking dashboard cares
        # about) over working through its back catalog.
        newest_first_ids = [
            row[0]
            for row in db.query(Video.id)
            .filter(Video.channel_id == channel.id)
            .order_by(Video.published_at.desc())
            .all()
        ]
        stats.sponsor_checks_made = check_and_store_sponsor_segments(db, settings, newest_first_ids, budget)

    stats.quota_units_used = client.quota_units_used
    return stats
