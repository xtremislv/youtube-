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

Two-call refresh pattern (mirrors scrapers/youtube.py's playlistItems.list
+ videos.list split): ``fetch_profile_posts`` discovers whatever's
currently in the account's most recent ``apify_max_posts_per_channel``
timeline items, but that alone would let an older tracked reel's view
count go permanently stale the moment it ages out of that window — an
account that posts a lot of photos between reels can push a reel out of a
30-item window well before the overperformance baseline's trailing
``baseline_window_videos`` (default 10) is done needing fresh numbers from
it, and Instagram views (like YouTube's) keep accruing for weeks after
publish, not just on day one. ``scrape_channel`` below closes that gap
with a second, targeted call — ``fetch_posts_by_url`` — that re-fetches
current stats for specifically the channel's most-recently-published
tracked reels that the discovery batch didn't already cover, by passing
their known post URLs straight to the same actor's ``directUrls`` input
(confirmed to accept individual ``/p/`` and ``/reel/`` URLs, not just
profile URLs). It's skipped entirely when discovery already covered
everything the baseline window needs, which is the common case for
reel-heavy accounts, so the extra cost is proportional to how much a
channel's actual mix of content pushes reels out of the discovery window.

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

from app.error_safety import safe_error_message
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

    def fetch_posts_by_url(self, urls: list[str]) -> list[dict]:
        """
        Refreshes specific already-known post/reel URLs, regardless of
        where (or whether) they currently sit in the account's timeline —
        the Instagram equivalent of scrapers/youtube.py's batched
        ``videos.list`` refresh call. See this module's docstring for why
        ``fetch_profile_posts`` alone isn't enough to keep the
        overperformance baseline's trailing window current.
        """
        if not urls:
            return []
        run_input: dict[str, Any] = {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": len(urls),
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
        "external_url": _safe_external_url(
            _first_present(raw, "url", default=None), f"https://www.instagram.com/p/{shortcode}/"
        ),
        "views": int(views),
        "likes": _int_or_none(_first_present(raw, "likesCount", "likes")),
        "comments": _int_or_none(_first_present(raw, "commentsCount", "comments")),
        "published_at": published_at,
        "duration_seconds": int(float(duration)) if duration else 0,
        "format": "reel",
    }


def _safe_external_url(raw_url: Any, fallback: str) -> str:
    """Only ever store an http(s) URL as Video.external_url — this value is
    later rendered as a clickable ``<a href>`` on the dashboard's video card
    (see src/App.tsx's VideoCard) with no further validation on that end.
    ``raw_url`` comes straight off a rented Apify actor's output, whose
    schema "is not standardized... and changes when actor authors update
    them" (this module's docstring) — a misbehaving or compromised actor
    returning something like a ``javascript:`` URI in its ``url`` field
    would otherwise become a stored-XSS payload the moment a teammate
    clicks that video. Anything that isn't a plain http(s) URL falls back
    to the same canonical post URL already used when the actor omits a
    ``url`` field entirely, so this changes behavior only for input that
    was never a valid link to begin with.
    """
    if isinstance(raw_url, str) and raw_url.strip().lower().startswith(("http://", "https://")):
        return raw_url
    return fallback


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
    videos_refreshed: int = 0
    runs_started: int = 0
    errors: list[str] = field(default_factory=list)


def _urls_needing_refresh(db: Session, channel_id: str, *, exclude_ids: set[str], limit: int) -> list[str]:
    """
    The channel's ``limit`` most-recently-published tracked reels that
    ``exclude_ids`` (whatever the discovery batch already just refreshed)
    doesn't already cover — exactly the videos the overperformance
    baseline's trailing window would otherwise be reading stale views from.

    Over-fetches by ``len(exclude_ids)`` rows before filtering: since at
    most ``len(exclude_ids)`` of the top ``limit + len(exclude_ids)`` most
    recent reels can be excluded, at least ``limit`` are guaranteed to
    remain (or fewer only if the channel simply doesn't have that many
    reels tracked yet).
    """
    if limit <= 0:
        return []
    rows = (
        db.query(Video.id, Video.external_url)
        .filter(Video.channel_id == channel_id, Video.format == "reel")
        .order_by(Video.published_at.desc())
        .limit(limit + len(exclude_ids))
        .all()
    )
    urls: list[str] = []
    for video_id, external_url in rows:
        if video_id in exclude_ids or not external_url:
            continue
        urls.append(external_url)
        if len(urls) >= limit:
            break
    return urls


def scrape_channel(client: ApifyInstagramClient, db: Session, channel: Channel, *, settings) -> ChannelScrapeStats:
    stats = ChannelScrapeStats()
    username = normalize_handle(channel.external_id, "instagram")

    try:
        items = client.fetch_profile_posts(username, max_posts=settings.apify_max_posts_per_channel)
    except Exception as exc:  # noqa: BLE001 — a single channel's actor failure shouldn't kill the batch
        stats.errors.append(f"Apify run failed for @{username}: {safe_error_message(exc)}")
        stats.runs_started = client.runs_started
        return stats

    meta = parse_profile_meta(items)
    if meta.get("name"):
        channel.name = meta["name"]
    if meta.get("avatar_initials"):
        channel.avatar_initials = meta["avatar_initials"]
    if meta.get("subscriber_count") is not None:
        channel.subscriber_count = meta["subscriber_count"]

    discovered_ids: set[str] = set()
    for raw_item in items:
        parsed = normalize_instagram_item(raw_item, channel_id=channel.id)
        if parsed is None:
            continue
        discovered_ids.add(parsed["id"])
        existing = db.get(Video, parsed["id"])
        if existing is None:
            db.add(Video(**parsed))
        else:
            for key, value in parsed.items():
                setattr(existing, key, value)
        stats.videos_upserted += 1

    # Second call — refresh whichever of this channel's most-recently-
    # published tracked reels the discovery batch above didn't already
    # cover. Needs a flush first so the discovery batch's own new rows
    # (e.g. a reel published since the last run) are visible to this
    # query too, not just previously-committed ones.
    db.flush()
    stale_urls = _urls_needing_refresh(
        db, channel.id, exclude_ids=discovered_ids, limit=settings.baseline_window_videos
    )
    if stale_urls:
        try:
            refresh_items = client.fetch_posts_by_url(stale_urls)
        except Exception as exc:  # noqa: BLE001 — the discovery batch already staged above shouldn't be lost
            stats.errors.append(f"Apify refresh run failed for @{username}: {safe_error_message(exc)}")
            refresh_items = []
        for raw_item in refresh_items:
            parsed = normalize_instagram_item(raw_item, channel_id=channel.id)
            if parsed is None:
                continue
            existing = db.get(Video, parsed["id"])
            if existing is None:
                # Shouldn't normally happen (these URLs came from videos we
                # already track), but upsert rather than assume.
                db.add(Video(**parsed))
            else:
                for key, value in parsed.items():
                    setattr(existing, key, value)
            # Folded into videos_upserted too (matching scrapers/youtube.py's
            # scrape_channel, which counts every touched row the same way —
            # "upserted" there already means "inserted or refreshed") so the
            # dashboard's existing "videos upserted" total keeps meaning
            # "total rows touched this run" for both platforms; kept as its
            # own counter as well since it's specifically what closes the
            # stale-baseline gap this whole call exists for.
            stats.videos_upserted += 1
            stats.videos_refreshed += 1

    db.flush()
    recompute_and_store_channel_baselines(db, channel.id, settings)
    stats.runs_started = client.runs_started
    return stats
