"""
Instagram scraper, via an Apify Actor rather than talking to Instagram
directly.

Why Apify and not a raw scraper: Instagram has no free official API that
lets a third party pull an arbitrary public competitor's posts (the
official Graph API only exposes accounts you administer, behind app
review). Community scrapers (instaloader, playwright-based scripts) work
but are fragile — Instagram aggressively rate-limits and IP-bans scraper
traffic, so they need proxies and constant maintenance to stay working.
Apify runs managed actors that handle that anti-blocking layer for you, in
exchange for metered usage (the free plan includes $5/month of usage
credit — see PRODUCTION_ROADMAP.md for what that buys).

Same split as scrapers/youtube.py: ``ApifyInstagramClient`` is the only
thing that talks to the network; ``normalize_instagram_item`` is a pure
function tests can feed realistic sample JSON without any credentials.

IMPORTANT — Apify actor output schemas are not standardized across actors
and change when actor authors update them. ``normalize_instagram_item``
below is written against the commonly-used ``apify/instagram-scraper`` and
``apify/instagram-reel-scraper`` field names (it tries several known aliases
per field). If you rent a different actor, open one dataset item in the
Apify console, compare its keys to the aliases below, and extend the
``_first_present`` lookups — that's the one place this integration is
actor-specific.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from apify_client import ApifyClient
from sqlalchemy.orm import Session

from app.formatting import initials_from_name, normalize_handle
from app.models import Channel, Video
from app.overperformance import recompute_and_store_channel_baselines

logger = logging.getLogger(__name__)


class ApifyInstagramClient:
    def __init__(self, api_token: str, actor_id: str):
        if not api_token:
            raise ValueError("APIFY_API_TOKEN is not set — see backend/.env.example")
        self._client = ApifyClient(api_token)
        self.actor_id = actor_id
        self.runs_started = 0

    def fetch_profile_posts(self, username: str, *, max_posts: int) -> list[dict]:
        """
        Runs the configured actor for one username and returns its dataset
        items. Blocks until the run finishes (Apify's ``.call()`` polls for
        you). Raises whatever ``apify_client`` raises on a failed run — the
        caller (scrape_channel) turns that into a per-channel error instead
        of aborting the whole batch.
        """
        run_input: dict[str, Any] = {
            "directUrls": [f"https://www.instagram.com/{username}/"],
            "resultsType": "posts",
            "resultsLimit": max_posts,
        }
        run = self._client.actor(self.actor_id).call(run_input=run_input)
        self.runs_started += 1
        dataset_id = run["defaultDatasetId"]
        return list(self._client.dataset(dataset_id).iterate_items())


# ── Pure parsing ─────────────────────────────────────────────────────────────


def _first_present(item: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def normalize_instagram_item(raw: dict, *, channel_id: str) -> dict | None:
    """
    Normalize one Apify dataset item into the app's Video shape. Returns
    None for an item that isn't actually a video/reel (a plain photo post
    has no meaningful "views" metric to track for overperformance) — photo
    carousels are skipped rather than force-fit into the schema.
    """
    post_id = _first_present(raw, "id", "shortCode", "pk")
    if not post_id:
        return None

    is_video = bool(_first_present(raw, "isVideo", "videoUrl", "videoDuration", default=False)) or _first_present(
        raw, "type", "productType", default=""
    ) in ("Video", "clips", "reel")
    if not is_video:
        return None

    views = _first_present(raw, "videoPlayCount", "videoViewCount", "playCount", "viewCount", default=None)
    if views is None:
        # Some actors only expose likes+comments for older posts; treat the
        # video as untracked-for-views rather than fabricating a number.
        return None

    timestamp = _first_present(raw, "timestamp", "takenAt", "takenAtTimestamp")
    published_at = _parse_instagram_timestamp(timestamp)

    caption = _first_present(raw, "caption", "text", "title", default="(no caption)")
    title = caption.splitlines()[0][:200] if caption else "(no caption)"

    shortcode = _first_present(raw, "shortCode", "code", default=post_id)
    duration = _first_present(raw, "videoDuration", default=0) or 0

    return {
        "id": f"instagram:{post_id}",
        "channel_id": channel_id,
        "platform": "instagram",
        "title": title,
        "thumbnail_url": _first_present(raw, "displayUrl", "thumbnailUrl", "thumbnailSrc"),
        "external_url": _first_present(raw, "url", default=f"https://www.instagram.com/p/{shortcode}/"),
        "views": int(views),
        "likes": _int_or_none(_first_present(raw, "likesCount", "likes")),
        "comments": _int_or_none(_first_present(raw, "commentsCount", "comments")),
        "published_at": published_at,
        "duration_seconds": int(float(duration)) if duration else 0,
        "format": "reel",
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_instagram_timestamp(value: Any) -> dt.date:
    if value is None:
        return dt.date.today()
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).date()
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return dt.date.today()


def parse_profile_meta(items: list[dict]) -> dict:
    """Best-effort profile info (name/followers) lifted off the first item,
    since most Instagram actors embed the profile owner on every post."""
    if not items:
        return {}
    first = items[0]
    owner = first.get("ownerFullName") or first.get("fullName") or first.get("username") or ""
    followers = _first_present(first, "followersCount", "ownerFollowersCount")
    return {
        "name": owner or None,
        "avatar_initials": initials_from_name(owner) if owner else None,
        "subscriber_count": _int_or_none(followers),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


@dataclass
class ChannelScrapeStats:
    videos_upserted: int = 0
    runs_started: int = 0
    errors: list[str] = field(default_factory=list)


def scrape_channel(client: ApifyInstagramClient, db: Session, channel: Channel, *, settings) -> ChannelScrapeStats:
    stats = ChannelScrapeStats()
    username = normalize_handle(channel.external_id, "instagram")

    try:
        items = client.fetch_profile_posts(username, max_posts=settings.apify_max_posts_per_channel)
    except Exception as exc:  # noqa: BLE001 — a single channel's actor failure shouldn't kill the batch
        stats.errors.append(f"Apify run failed for @{username}: {exc}")
        stats.runs_started = client.runs_started
        return stats

    meta = parse_profile_meta(items)
    if meta.get("name"):
        channel.name = meta["name"]
    if meta.get("avatar_initials"):
        channel.avatar_initials = meta["avatar_initials"]
    if meta.get("subscriber_count") is not None:
        channel.subscriber_count = meta["subscriber_count"]

    for raw_item in items:
        parsed = normalize_instagram_item(raw_item, channel_id=channel.id)
        if parsed is None:
            continue
        existing = db.get(Video, parsed["id"])
        if existing is None:
            db.add(Video(**parsed))
        else:
            for key, value in parsed.items():
                setattr(existing, key, value)
        stats.videos_upserted += 1

    db.flush()
    recompute_and_store_channel_baselines(db, channel.id, settings)
    stats.runs_started = client.runs_started
    return stats
