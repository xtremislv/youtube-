"""
SponsorBlock integration (https://wiki.sponsor.ajay.app/w/API_Docs) — a
free, crowdsourced, YouTube-only database of timestamped segments inside
videos: sponsor reads, self-promo plugs, paid "exclusive access" pitches,
and a few purely structural categories (intro/outro/preview/filler/etc.)
this dashboard doesn't care about. This module checks which of a channel's
videos have a commercially-relevant segment, so the dashboard can flag
"this competitor's video is a sponsored/campaign video" without watching
it.

There is no equivalent public database for Instagram, so this only ever
runs from app/scrapers/youtube.py — Instagram videos simply never get a
sponsor check and always read as "no data".

Split the same way as app/scrapers/youtube.py, for the same reason (the
part worth unit-testing shouldn't need the network):
- ``SponsorBlockClient`` — the only thing here that talks to the network.
- ``parse_segments()`` — pure function: raw segment JSON -> a summary.
- ``check_and_store_sponsor_segments()`` — orchestrates the two against the
  DB for a batch of videos, respecting a shared per-run budget so one big
  channel backfill can't burn through SponsorBlock's free API or blow the
  scrape job's time limit (see SponsorCheckBudget below).

Licensing note: SponsorBlock's database is community-contributed and
distributed under its own license, which requires attribution — see the
"Sponsor data via SponsorBlock" credit + link in the dashboard's sidebar
(src/App.tsx). If this dashboard's use ever stops being "an internal tool a
small team looks at" and becomes something redistributed/sold, re-check
https://wiki.sponsor.ajay.app for whether that still fits the license
before relying on this module.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# The full category vocabulary SponsorBlock supports (see the API docs'
# "Category" list) — kept here for reference/validation even though only
# Settings.sponsorblock_category_list (a subset) is actually queried/counted.
ALL_CATEGORIES = {
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "preview",
    "music_offtopic",
    "poi_highlight",
    "filler",
    "exclusive_access",
    "chapter",
}

REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass
class SponsorSummary:
    has_sponsor: bool
    sponsor_seconds: float


def parse_segments(raw_segments: list[dict], counted_categories: set[str]) -> SponsorSummary:
    """
    ``raw_segments`` is the JSON array GET /api/skipSegments returns — each
    item has a ``category`` and a ``segment: [startSeconds, endSeconds]``
    (see the API docs). Sums the duration of every segment whose category
    is in ``counted_categories``. Overlapping segments are summed as given
    rather than merged first, which can slightly over-count in the rare
    case two counted categories overlap the same seconds — an acceptable
    simplification for a "roughly how much of this video is sponsored"
    indicator, not a frame-accurate one.
    """
    total = 0.0
    for seg in raw_segments:
        if seg.get("category") not in counted_categories:
            continue
        bounds = seg.get("segment") or [0, 0]
        start, end = bounds[0], bounds[1]
        if end > start:
            total += end - start
    return SponsorSummary(has_sponsor=total > 0, sponsor_seconds=round(total, 1))


class SponsorBlockRateLimited(Exception):
    """Raised on a 429 — the caller should stop checking more videos this
    run rather than keep hammering a rate limit."""


class SponsorBlockClient:
    def __init__(self, base_url: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def get_segments(self, youtube_video_id: str, categories: list[str]) -> list[dict]:
        """
        Raw segment list for one video, or ``[]`` if SponsorBlock has no
        submissions for it (a 404 — the common case for a small/fresh
        channel, not an error). Any failure other than a 429 (network
        error, timeout, 5xx, unparseable body) is logged and also treated
        as "no data available right now" rather than raised, since a
        third-party API hiccup shouldn't abort an otherwise-fine channel
        scrape.
        """
        try:
            resp = self._client.get(
                f"{self._base_url}/api/skipSegments",
                params={"videoID": youtube_video_id, "category": categories},
            )
        except httpx.HTTPError as exc:
            logger.warning("SponsorBlock request failed for %s: %s", youtube_video_id, exc)
            return []

        if resp.status_code == 404:
            return []
        if resp.status_code == 429:
            raise SponsorBlockRateLimited(f"SponsorBlock rate-limited this request (video {youtube_video_id})")
        if resp.status_code != 200:
            logger.warning("SponsorBlock returned HTTP %s for %s", resp.status_code, youtube_video_id)
            return []

        try:
            return resp.json()
        except ValueError:
            logger.warning("SponsorBlock returned unparseable JSON for %s", youtube_video_id)
            return []

    def close(self) -> None:
        self._client.close()


class SponsorCheckBudget:
    """A shared "how many more SponsorBlock lookups may this scrape run
    make" counter, passed down through every channel in one platform run
    (see app/scrape_service.py) so a single channel with hundreds of
    unchecked videos can't eat the whole run's time/rate-limit budget —
    whatever's left over just gets picked up on a later scrape, since
    unchecked videos stay unchecked (sponsor_checked_at stays null) until
    they're actually checked."""

    def __init__(self, limit: int):
        self.remaining = max(0, limit)

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def check_and_store_sponsor_segments(
    db,
    settings,
    video_ids: list[str],
    budget: SponsorCheckBudget,
    client: "SponsorBlockClient | object | None" = None,
) -> int:
    """
    For each of ``video_ids`` (DB ids, e.g. "youtube:dQw4w9WgXcQ") that
    exists, isn't stale-checked (see Settings.sponsorblock_recheck_hours),
    and while ``budget`` allows it: look up its SponsorBlock segments and
    write has_sponsor_segment/sponsor_segment_seconds/sponsor_checked_at
    onto the ORM object (caller is responsible for committing — matches
    recompute_and_store_channel_baselines's contract). Returns how many
    videos were actually checked (network calls made), for logging/tests.

    ``video_ids`` is checked in the order given — pass it newest-first so a
    tight budget prioritizes a channel's most recent uploads over its back
    catalog, since that's what a competitor-tracking dashboard cares about
    most.

    ``client`` defaults to a real ``SponsorBlockClient``; tests pass a fake
    object exposing the same ``get_segments(video_id, categories) -> list``
    method so this can be verified without hitting the network.
    """
    from app.models import Video  # local import: mirrors overperformance.py's pattern, keeps this DB-import-free for pure unit tests

    if not settings.sponsorblock_enabled:
        return 0
    categories = settings.sponsorblock_category_list
    if not categories:
        return 0

    owns_client = client is None
    sb_client = client or SponsorBlockClient(settings.sponsorblock_api_base)
    checked = 0
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=settings.sponsorblock_recheck_hours)
        for video_id in video_ids:
            if not budget.take():
                break
            video = db.get(Video, video_id)
            if video is None or video.platform != "youtube":
                continue

            checked_at = video.sponsor_checked_at
            if checked_at is not None:
                # Postgres hands back a tz-aware datetime for a
                # DateTime(timezone=True) column; SQLite (tests) always
                # hands back naive regardless of column type — coerce to
                # aware-UTC before comparing so this never raises "can't
                # compare offset-naive and offset-aware datetimes" (see the
                # identical fix in routers/scrape.py).
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=dt.timezone.utc)
                if checked_at >= cutoff:
                    continue

            external_id = video_id.removeprefix("youtube:")
            try:
                raw_segments = sb_client.get_segments(external_id, categories)
            except SponsorBlockRateLimited:
                logger.info("SponsorBlock rate-limited — stopping sponsor checks for the rest of this run")
                break

            checked += 1
            summary = parse_segments(raw_segments, set(categories))
            video.has_sponsor_segment = summary.has_sponsor
            video.sponsor_segment_seconds = summary.sponsor_seconds if summary.has_sponsor else None
            video.sponsor_checked_at = dt.datetime.utcnow()
    finally:
        if owns_client:
            sb_client.close()

    return checked
