"""
Early-velocity tracking: judging a brand-new upload against how a channel's
*own* recent videos typically looked at the same age, not just its eventual
lifetime total — see the "h1/h3/h6" columns on ``Video`` in app/models.py.

Deliberately independent of app/overperformance.py's baseline pipeline: this
module never reads or writes ``views``/``avg_views_baseline``/
``overperform_ratio``, only the velocity-specific columns/table, so nothing
here can affect the existing (well-tested) overperformance math. It mirrors
that module's shape on purpose though — a pure "just data in, data out"
function plus a thin DB-facing orchestration wrapper — for the same reason:
the part worth unit-testing shouldn't need a database or the network.

Pieces:
- ``VelocityVideoInput`` / ``VelocityBaselineResult`` / ``compute_velocity_
  baselines()`` — pure function: given every video's per-checkpoint view
  counts (only the checkpoints that have actually been captured), work out
  each video's ratio against a trailing per-(channel implied by caller,
  format, checkpoint) baseline. Same trailing-window/min-videos gating as
  overperformance.py, reusing its settings (``baseline_window_videos`` /
  ``baseline_min_videos``) rather than adding a second set of knobs.
- ``recompute_and_store_channel_velocity_baselines()`` — DB-facing wrapper
  matching ``recompute_and_store_channel_baselines``'s contract (caller
  commits).
- ``capture_velocity_snapshots()`` — the actual hourly job body (see
  routers/scrape.py's POST /api/scrape/check-velocity and .github/
  workflows/hourly-velocity-check.yml): finds YouTube videos that still
  have an open checkpoint window, refreshes their view/like/comment counts
  in one batched ``videos.list`` call, records whichever checkpoint(s) now
  fall inside their grace window, and recomputes velocity baselines for
  every channel touched. A checkpoint whose grace window closes with
  nothing captured is left permanently null — see Settings.
  velocity_checkpoint_grace_hours's docstring — never backfilled later from
  by-then-stale data.

Known Phase-1 limitation: unlike the main scrape (see app/scrape_service.py),
this job does not write a ScrapeRun row, so its (small — well under 50 units/
day, see backend/README.md's quota math) YouTube quota spend doesn't show up
in the sidebar's "API Quota" widget. Acceptable for a backend-only first cut;
worth revisiting if that widget needs to be exact.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.scrapers.youtube import YouTubeClient


@dataclass
class VelocityVideoInput:
    """The minimum a video needs to participate in velocity-baseline math.
    ``checkpoint_views`` only has entries for checkpoints already captured
    for this video (e.g. ``{1: 500}`` for a video that's only hit its 1h
    mark so far) — a missing/not-yet-captured checkpoint must never be
    treated as 0 views, so it's simply absent rather than None-valued."""

    id: str
    format: str
    # The full publish instant, not just the date — unlike overperformance.
    # BaselineInput (which predates published_at_ts and sorts by date only),
    # velocity checkpoints are captured on an hourly cadence, so same-day
    # publishes are common and a date-only sort key would frequently order
    # them arbitrarily (by id) instead of chronologically, corrupting which
    # videos count as "prior" for the trailing window. Callers must pass a
    # value that's comparable across every video given in one call — see
    # recompute_and_store_channel_velocity_baselines's naive/aware coercion.
    published_at: dt.datetime
    checkpoint_views: dict[int, int]


@dataclass
class VelocityBaselineResult:
    id: str
    checkpoint_ratios: dict[int, float]  # only for checkpoints VelocityVideoInput had captured


def compute_velocity_baselines(
    videos: list[VelocityVideoInput],
    *,
    window: int = 10,
    min_videos: int = 3,
) -> list[VelocityBaselineResult]:
    """
    Mirrors overperformance.compute_baselines's shape, but keeps one
    trailing window *per checkpoint hour* rather than one window per format
    — a video that missed its 1h checkpoint but caught its 3h one should
    still contribute to the 3h trailing baseline, and shouldn't silently
    drag the 1h baseline down by counting as a 0.

    Callers should pass in all of one channel's videos (across all
    formats) — this buckets by ``format`` itself, same as overperformance,
    since a channel's Shorts and long-form videos naturally sit at very
    different view counts at every checkpoint too.
    """
    by_format: dict[str, list[VelocityVideoInput]] = {}
    for v in videos:
        by_format.setdefault(v.format, []).append(v)

    ratios_by_id: dict[str, dict[int, float]] = {v.id: {} for v in videos}

    for _, group in by_format.items():
        ordered = sorted(group, key=lambda v: (v.published_at, v.id))
        # One trailing list of prior views per checkpoint hour, scoped to
        # this format group.
        windows: dict[int, list[int]] = {}
        for v in ordered:
            for checkpoint_hours, views in v.checkpoint_views.items():
                trailing = windows.setdefault(checkpoint_hours, [])
                if len(trailing) >= min_videos:
                    window_slice = trailing[-window:]
                    baseline = sum(window_slice) / len(window_slice)
                    if baseline > 0:
                        ratios_by_id[v.id][checkpoint_hours] = views / baseline
                trailing.append(views)

    return [VelocityBaselineResult(id=v.id, checkpoint_ratios=ratios_by_id[v.id]) for v in videos]


def recompute_and_store_channel_velocity_baselines(db: "Session", channel_id: str, settings) -> None:
    """
    Reload every YouTube video the DB has for one channel, recompute
    velocity ratios with compute_velocity_baselines(), and write them back
    onto the h{N}_ratio columns of the ORM objects (caller commits) — same
    contract as recompute_and_store_channel_baselines.
    """
    from app.models import Video  # local import: keeps this module DB-import-free for pure unit tests

    checkpoints = settings.velocity_checkpoint_hours_list
    if not checkpoints:
        return

    videos = db.query(Video).filter(Video.channel_id == channel_id, Video.platform == "youtube").all()
    inputs = []
    for v in videos:
        checkpoint_views = {}
        for h in checkpoints:
            value = getattr(v, f"h{h}_views", None)
            if value is not None:
                checkpoint_views[h] = value

        published_ts = v.published_at_ts
        if published_ts is None:
            # Pre-migration row with no timestamp (see Video.published_at_ts's
            # docstring) — falls back to midnight UTC on its known date. Such
            # a video will also have no checkpoint_views (velocity is a new
            # feature), so it never actually enters a trailing window; this
            # is just enough of a sort key to not crash.
            published_ts = dt.datetime.combine(v.published_at, dt.time.min, tzinfo=dt.timezone.utc)
        elif published_ts.tzinfo is None:
            # Postgres hands back aware datetimes for this column; SQLite
            # (tests) always hands back naive ones regardless of column type
            # — same coercion used throughout this project (see
            # routers/scrape.py, app/sponsorblock.py).
            published_ts = published_ts.replace(tzinfo=dt.timezone.utc)

        inputs.append(VelocityVideoInput(id=v.id, format=v.format, published_at=published_ts, checkpoint_views=checkpoint_views))

    results = {
        r.id: r
        for r in compute_velocity_baselines(
            inputs,
            window=settings.baseline_window_videos,
            min_videos=settings.baseline_min_videos,
        )
    }
    for v in videos:
        ratios = results[v.id].checkpoint_ratios if v.id in results else {}
        for h in checkpoints:
            attr = f"h{h}_ratio"
            if hasattr(v, attr):  # only true for the checkpoints models.py actually has columns for
                setattr(v, attr, ratios.get(h))


def _extract_stats(raw_video: dict) -> tuple[int, int | None, int | None]:
    """views/likes/comments out of a raw videos.list item — deliberately
    separate from app.scrapers.youtube.parse_video_resource (which also
    computes duration/format/thumbnail/etc. this job doesn't need) rather
    than importing it, so this module stays a thin, independent consumer of
    the same client."""
    stats = raw_video.get("statistics", {})
    views = int(stats.get("viewCount", 0) or 0)
    likes = int(stats["likeCount"]) if "likeCount" in stats else None
    comments = int(stats["commentCount"]) if "commentCount" in stats else None
    return views, likes, comments


@dataclass
class VelocityCheckStats:
    videos_checked: int = 0
    checkpoints_captured: int = 0
    channels_recomputed: int = 0
    errors: list[str] = field(default_factory=list)


def capture_velocity_snapshots(
    db: "Session",
    settings,
    client: "YouTubeClient | None" = None,
) -> VelocityCheckStats:
    """
    The hourly job body. Finds every YouTube video published recently
    enough that at least one of its checkpoints (Settings.
    velocity_checkpoints_hours) hasn't yet been captured *and* hasn't yet
    aged past its grace window either, refreshes their stats in one batch,
    and records whichever checkpoint(s) now fall inside their window.

    ``client`` defaults to a real YouTubeClient (built from
    settings.youtube_api_key); tests pass a fake exposing the same
    ``get_videos(ids) -> list[dict]`` method, mirroring the SponsorBlock/
    overperformance testing pattern.
    """
    from app.models import Video, VideoVelocitySnapshot  # local import: keeps this module DB-import-free for pure unit tests

    stats = VelocityCheckStats()

    checkpoints = settings.velocity_checkpoint_hours_list
    if not checkpoints:
        return stats
    grace = settings.velocity_checkpoint_grace_hours
    now = dt.datetime.now(dt.timezone.utc)

    # No SQL-side date filter here on purpose: comparing a tz-aware Python
    # datetime against a DateTime(timezone=True) column mixes badly with
    # SQLite's naive-string storage (used in tests), the same "offset-naive
    # vs offset-aware" trap this project works around elsewhere (see
    # routers/scrape.py, app/sponsorblock.py) — except this time it'd be
    # inside the SQL layer, not a Python comparison, so it can't be fixed
    # with the usual .tzinfo coercion. Simpler and safer to fetch every
    # not-yet-fully-resolved YouTube video and do the precise per-checkpoint
    # elapsed-hours math in Python below. This table isn't expected to be
    # large enough for that to matter.
    candidates = (
        db.query(Video)
        .filter(Video.platform == "youtube", Video.published_at_ts.isnot(None))
        .all()
    )

    open_videos: list[tuple[Video, float]] = []
    for v in candidates:
        published = v.published_at_ts
        if published.tzinfo is None:
            published = published.replace(tzinfo=dt.timezone.utc)
        hours_since = (now - published).total_seconds() / 3600
        if hours_since < 0:
            continue  # clock skew / not actually published yet — skip rather than error
        has_open_checkpoint = any(
            getattr(v, f"h{h}_views", None) is None and hours_since <= h + grace for h in checkpoints
        )
        if has_open_checkpoint:
            open_videos.append((v, hours_since))

    if not open_videos:
        return stats

    owns_client = client is None
    if client is not None:
        yt_client = client
    else:
        from app.scrapers.youtube import YouTubeClient

        yt_client = YouTubeClient(settings.youtube_api_key)

    try:
        external_ids = [video.id.removeprefix("youtube:") for video, _ in open_videos]
        raw_videos = yt_client.get_videos(external_ids)
        raw_by_id = {raw["id"]: raw for raw in raw_videos}

        touched_channel_ids: set[str] = set()
        for video, hours_since in open_videos:
            raw = raw_by_id.get(video.id.removeprefix("youtube:"))
            if raw is None:
                # Deleted/privated since it was first tracked — nothing to
                # capture; leave its checkpoints to age into "missed".
                continue
            stats.videos_checked += 1
            views, likes, comments = _extract_stats(raw)
            video.velocity_checked_at = now
            for h in checkpoints:
                if getattr(video, f"h{h}_views", None) is not None:
                    continue
                if hours_since < h or hours_since > h + grace:
                    continue
                setattr(video, f"h{h}_views", views)
                db.add(
                    VideoVelocitySnapshot(
                        video_id=video.id,
                        checkpoint_hours=h,
                        views=views,
                        likes=likes,
                        comments=comments,
                        captured_at=now,
                        hours_since_publish=hours_since,
                    )
                )
                stats.checkpoints_captured += 1
            touched_channel_ids.add(video.channel_id)

        db.flush()
        for channel_id in touched_channel_ids:
            recompute_and_store_channel_velocity_baselines(db, channel_id, settings)
        stats.channels_recomputed = len(touched_channel_ids)
    finally:
        if owns_client:
            close = getattr(yt_client, "close", None)
            if callable(close):
                close()

    return stats
