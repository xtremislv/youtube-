"""
Topic search — "is this topic trending on YouTube right now", a
user-triggered lookup that is deliberately separate from the tracked-
channel scrape pipeline (app/scrapers/*.py, app/overperformance.py).

Method:

1. ``search.list`` the query, restricted to a caller-chosen date range
   (``date_from``/``date_to`` — the Trend Analysis tab's date filter,
   defaulting to the last 30 days; either end can be left unset for an
   open-ended "All time" search) and region-scoped to a caller-chosen
   ``region_code`` (``None`` = "Global", no regionCode sent at all). This
   is the one expensive call (100 quota units flat) — see
   YouTubeClient.search_videos()'s docstring for why nothing else in this
   app uses it. ``app/config.py``'s ``search_lookback_days``/
   ``search_region_code`` only apply as fallback defaults when a caller
   (e.g. a direct API request) omits these entirely — see
   app/routers/search.py, which resolves the Trend Analysis tab's request
   body against them before calling ``run_topic_search``.
2. Fetch view counts (``videos.list``) and subscriber counts
   (``channels.list``) for every result, batched.
3. Gate: drop any video whose channel has fewer than a caller-chosen
   ``min_subscribers`` threshold (defaulting to 500K — also a Trend
   Analysis tab filter now) subscribers, or a hidden subscriber count
   (which can't be gated at all) — keeps one small channel's lucky video
   from dominating the read.
4. Score every surviving video with ``score_candidate()`` — views per
   subscriber per day since publish, i.e. "how hard is this moving,
   normalized for channel size and how long it's had to accumulate
   views" — then keep only each channel's single best-scoring video and
   take the top ``search_top_n_channels`` channels.
5. For those channels only (not the whole candidate pool — this is the
   part that would get expensive if done for everyone): walk their
   uploads playlist (cheap — ``playlistItems.list``, 1 unit/page, never
   another ``search.list``) to get their own recent upload history,
   exclude the candidate video itself, and compute a real channel-median
   comparison — the same "is this one video unusually big for this
   channel" math as app/overperformance.py, just computed live instead of
   from persisted history.

Nothing from a search is added to the tracked Channel/Video tables. Only a
single-slot cache survives (see TopicSearchCache/TopicSearchCacheChannel
in app/models.py): the latest query's summary + its top channels, fully
replaced on every new search. Repeating an identical query still searches
YouTube fresh — the cache's only job is to survive a page reload, not to
avoid re-spending quota on a repeat query, since "is this trending right
now" goes stale by definition.

Split the same way as velocity.py/overperformance.py: pure scoring/ranking
functions with no DB or network dependency (fully unit-testable), and an
orchestration function that does the real API calls + persistence.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings


# ── Pure data shapes ─────────────────────────────────────────────────────────


@dataclass
class CandidateVideo:
    """One search result, joined with its channel's stats — everything
    needed to score and (if selected) display/persist it."""

    video_external_id: str
    title: str
    thumbnail_url: str | None
    video_url: str
    views: int
    published_at: dt.date

    channel_external_id: str
    channel_name: str
    channel_handle: str | None
    channel_avatar_url: str | None
    subscriber_count: int
    # Only used internally to fetch this channel's recent uploads for the
    # median comparison — never persisted.
    uploads_playlist_id: str | None = None


@dataclass
class RankedChannel:
    rank: int
    candidate: CandidateVideo
    score: float


@dataclass
class ResolvedChannel(RankedChannel):
    channel_median_views: float | None = None
    overperform_ratio: float | None = None
    is_outperforming: bool = False


@dataclass
class TopicSearchOutcome:
    query: str
    searched_at: dt.datetime
    date_from: dt.date | None
    date_to: dt.date | None
    lookback_days: int | None
    min_subscribers: int
    region_code: str | None
    top_n: int
    total_candidates: int
    outperform_count: int
    youtube_quota_units_used: int
    channels: list[ResolvedChannel]


# ── Pure scoring / ranking (no network, fully unit-testable) ────────────────


def score_candidate(*, views: int, subscriber_count: int, published_at: dt.date, now: dt.date) -> float:
    """views per subscriber per day-since-published.

    Dividing by subscriber count normalizes for channel size (a big
    channel needs proportionally more views to look "hyped" than a small
    one); dividing by days-since-published stops an 8-week-old video from
    automatically outranking a 3-day-old one just for having had longer to
    accumulate views — both were the two nuances explicitly asked for.
    ``days`` is floored at 1 so a video published today (or, in a test,
    "today" exactly) doesn't divide by zero or explode from one lucky
    early hour.
    """
    if subscriber_count <= 0:
        return 0.0
    days = max(1, (now - published_at).days)
    return (views / subscriber_count) / days


def select_top_channels(
    candidates: list[CandidateVideo],
    *,
    min_subscribers: int,
    top_n: int,
    now: dt.date,
) -> tuple[list[RankedChannel], int]:
    """Gate by subscriber count, score, keep each channel's single
    best-scoring video, and return the top ``top_n`` channels by that
    score — plus the total number of videos that survived the gate (the
    "out of N" denominator), before the dedup-to-top_n cut.
    """
    gated = [c for c in candidates if c.subscriber_count >= min_subscribers]

    scored = sorted(
        (
            (score_candidate(views=c.views, subscriber_count=c.subscriber_count, published_at=c.published_at, now=now), c)
            for c in gated
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )

    best_per_channel: dict[str, tuple[float, CandidateVideo]] = {}
    for score, c in scored:
        best_per_channel.setdefault(c.channel_external_id, (score, c))

    ordered = sorted(best_per_channel.values(), key=lambda pair: pair[0], reverse=True)[:top_n]
    ranked = [RankedChannel(rank=i + 1, candidate=c, score=s) for i, (s, c) in enumerate(ordered)]
    return ranked, len(gated)


def compute_median_performance(video_views: int, other_recent_views: list[int]) -> tuple[float | None, float | None]:
    """This channel's median views over its *other* recent uploads (the
    candidate video itself must already be excluded by the caller — see
    app/overperformance.py's identical "never including itself"
    principle), and this video's ratio against that median. ``(None,
    None)`` if there's nothing to compare against (a channel with no other
    recent uploads)."""
    if not other_recent_views:
        return None, None
    median = statistics.median(other_recent_views)
    ratio = (video_views / median) if median > 0 else None
    return median, ratio


def is_outperforming(ratio: float | None, threshold: float) -> bool:
    return ratio is not None and ratio >= threshold


def estimate_quota_cost(settings: "Settings") -> int:
    """Rough worst-case quota units one search will spend — search.list
    (100, flat) + videos.list/channels.list for the raw result page (1
    each) + top_n channels' median lookups (2 each: playlistItems.list +
    videos.list). Used by the router to refuse a search up front rather
    than fail partway through after already spending most of it."""
    return 100 + 1 + 1 + (settings.search_top_n_channels * 2)


# ── Orchestration (network + DB) ────────────────────────────────────────────


def run_topic_search(
    db: "Session",
    settings: "Settings",
    query: str,
    *,
    min_subscribers: int,
    region_code: str | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
) -> TopicSearchOutcome:
    """Runs one live search. ``min_subscribers``/``region_code``/
    ``date_from``/``date_to`` are the Trend Analysis tab's editable
    filters (see app/routers/search.py, which resolves the request body's
    optional overrides against ``settings``' defaults before calling this
    — by the time it gets here every value is already concrete): a
    ``region_code`` of ``None`` means no regional restriction ("Global"),
    and a ``date_from``/``date_to`` of ``None`` means no lower/upper bound
    on publish date ("All time" / "up to now", respectively).
    """
    from app.scrapers.youtube import YouTubeClient, parse_channel_resource, parse_video_resource

    client = YouTubeClient(settings.youtube_api_key)
    now = dt.datetime.now(dt.timezone.utc)
    published_after = (
        dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.timezone.utc) if date_from is not None else None
    )
    # Inclusive of the whole date_to day — YouTube's publishedBefore is a
    # strict "<" cutoff, so the bound is midnight at the *start* of the
    # following day, not end-of-day on date_to itself.
    published_before = (
        dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
        if date_to is not None
        else None
    )

    search_items = client.search_videos(
        query=query,
        published_after=published_after,
        published_before=published_before,
        region_code=region_code,
        max_results=settings.search_max_results,
    )

    channel_id_by_video: dict[str, str] = {}
    video_ids: list[str] = []
    for item in search_items:
        vid = item.get("id", {}).get("videoId")
        cid = item.get("snippet", {}).get("channelId")
        if vid and cid:
            video_ids.append(vid)
            channel_id_by_video[vid] = cid

    candidates: list[CandidateVideo] = []
    if video_ids:
        raw_videos = client.get_videos(video_ids)
        unique_channel_ids = list(dict.fromkeys(channel_id_by_video.values()))
        raw_channels = client.get_channels(unique_channel_ids)
        channels_by_id = {raw["id"]: parse_channel_resource(raw) for raw in raw_channels}

        for raw_video in raw_videos:
            raw_channel_id = channel_id_by_video.get(raw_video["id"])
            channel_info = channels_by_id.get(raw_channel_id) if raw_channel_id else None
            # Hidden subscriber count (channel opted out of showing it) or a
            # channel we somehow couldn't resolve — can't apply the gate at
            # all, so exclude rather than guess.
            if channel_info is None or channel_info["subscriber_count"] is None:
                continue
            parsed = parse_video_resource(raw_video, channel_id=raw_channel_id)
            candidates.append(
                CandidateVideo(
                    video_external_id=raw_video["id"],
                    title=parsed["title"],
                    thumbnail_url=parsed["thumbnail_url"],
                    video_url=parsed["external_url"],
                    views=parsed["views"],
                    published_at=parsed["published_at"],
                    channel_external_id=raw_channel_id,
                    channel_name=channel_info["name"],
                    channel_handle=None,
                    channel_avatar_url=channel_info["avatar_url"],
                    subscriber_count=channel_info["subscriber_count"],
                    uploads_playlist_id=channel_info["uploads_playlist_id"],
                )
            )

    ranked, total_candidates = select_top_channels(
        candidates,
        min_subscribers=min_subscribers,
        top_n=settings.search_top_n_channels,
        now=now.date(),
    )

    resolved: list[ResolvedChannel] = []
    for rc in ranked:
        c = rc.candidate
        median_views: float | None = None
        ratio: float | None = None
        if c.uploads_playlist_id:
            recent_ids = client.list_uploads_video_ids(c.uploads_playlist_id, max_pages=1)
            recent_ids = [v for v in recent_ids if v != c.video_external_id][: settings.baseline_window_videos]
            if recent_ids:
                raw_recent = client.get_videos(recent_ids)
                recent_views = [int(v.get("statistics", {}).get("viewCount", 0) or 0) for v in raw_recent]
                median_views, ratio = compute_median_performance(c.views, recent_views)
        resolved.append(
            ResolvedChannel(
                rank=rc.rank,
                candidate=c,
                score=rc.score,
                channel_median_views=median_views,
                overperform_ratio=ratio,
                is_outperforming=is_outperforming(ratio, settings.overperform_ratio_default),
            )
        )

    outcome = TopicSearchOutcome(
        query=query,
        searched_at=now,
        date_from=date_from,
        date_to=date_to,
        lookback_days=((date_to or now.date()) - date_from).days if date_from is not None else None,
        min_subscribers=min_subscribers,
        region_code=region_code,
        top_n=settings.search_top_n_channels,
        total_candidates=total_candidates,
        outperform_count=sum(1 for r in resolved if r.is_outperforming),
        youtube_quota_units_used=client.quota_units_used,
        channels=resolved,
    )
    _persist_outcome(db, outcome)
    return outcome


def _persist_outcome(db: "Session", outcome: TopicSearchOutcome) -> None:
    """Deletes the previous search's cache rows and writes the new ones,
    in one transaction — exactly one query's data ever exists at a time,
    per this module's single-slot caching design."""
    from app.models import TopicSearchCache, TopicSearchCacheChannel  # local import: keeps this module's pure functions DB-import-free for unit tests

    db.query(TopicSearchCacheChannel).delete()
    db.query(TopicSearchCache).delete()

    db.add(
        TopicSearchCache(
            id=1,
            query=outcome.query,
            searched_at=outcome.searched_at,
            date_from=outcome.date_from,
            date_to=outcome.date_to,
            lookback_days=outcome.lookback_days,
            min_subscribers=outcome.min_subscribers,
            region_code=outcome.region_code,
            top_n=outcome.top_n,
            total_candidates=outcome.total_candidates,
            outperform_count=outcome.outperform_count,
            youtube_quota_units_used=outcome.youtube_quota_units_used,
        )
    )
    for r in outcome.channels:
        c = r.candidate
        db.add(
            TopicSearchCacheChannel(
                rank=r.rank,
                channel_external_id=c.channel_external_id,
                channel_name=c.channel_name,
                channel_handle=c.channel_handle,
                channel_avatar_url=c.channel_avatar_url,
                subscriber_count=c.subscriber_count,
                video_external_id=c.video_external_id,
                video_title=c.title,
                video_thumbnail_url=c.thumbnail_url,
                video_url=c.video_url,
                video_views=c.views,
                video_published_at=c.published_at,
                rank_score=r.score,
                channel_median_views=r.channel_median_views,
                overperform_ratio=r.overperform_ratio,
                is_outperforming=r.is_outperforming,
            )
        )
    db.commit()


def get_cached_search(db: "Session") -> TopicSearchOutcome | None:
    """Reconstructs the current single-slot cache (if any) for GET
    /api/search/latest — the page-reload path that must never itself spend
    quota."""
    from app.models import TopicSearchCache, TopicSearchCacheChannel

    cache = db.get(TopicSearchCache, 1)
    if cache is None:
        return None

    rows = db.query(TopicSearchCacheChannel).order_by(TopicSearchCacheChannel.rank).all()
    channels = [
        ResolvedChannel(
            rank=row.rank,
            candidate=CandidateVideo(
                video_external_id=row.video_external_id,
                title=row.video_title,
                thumbnail_url=row.video_thumbnail_url,
                video_url=row.video_url,
                views=row.video_views,
                published_at=row.video_published_at,
                channel_external_id=row.channel_external_id,
                channel_name=row.channel_name,
                channel_handle=row.channel_handle,
                channel_avatar_url=row.channel_avatar_url,
                subscriber_count=row.subscriber_count,
            ),
            score=row.rank_score,
            channel_median_views=row.channel_median_views,
            overperform_ratio=row.overperform_ratio,
            is_outperforming=row.is_outperforming,
        )
        for row in rows
    ]

    return TopicSearchOutcome(
        query=cache.query,
        searched_at=cache.searched_at,
        date_from=cache.date_from,
        date_to=cache.date_to,
        lookback_days=cache.lookback_days,
        min_subscribers=cache.min_subscribers,
        region_code=cache.region_code,
        top_n=cache.top_n,
        total_candidates=cache.total_candidates,
        outperform_count=cache.outperform_count,
        youtube_quota_units_used=cache.youtube_quota_units_used,
        channels=channels,
    )
