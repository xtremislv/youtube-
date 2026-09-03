"""
The one piece of "business logic" this whole project has: deciding what a
channel's *normal* view count looks like, so a video can be judged against
it.

Method (deliberately simple and explainable — see PRODUCTION_ROADMAP.md for
ideas on making it fancier later):

For each (channel, format) pair — long-form YouTube videos, YouTube Shorts,
and Instagram Reels are tracked as separate baselines, since a channel's
Shorts and long-form videos naturally sit at very different view counts —
sort that channel's videos of that format by publish date. Each video's
baseline is the *trailing* mean views of up to ``BASELINE_WINDOW_VIDEOS``
videos published strictly before it (never including itself, and never
looking into the future). A video needs at least ``BASELINE_MIN_VIDEOS``
prior videos before a baseline is considered meaningful; before that its
``avg_views_baseline`` / ``overperform_ratio`` are left ``None`` rather than
computed from too little data (a brand-new channel's first video would
otherwise trivially "overperform" against an empty baseline).

``overperform_ratio = views / avg_views_baseline``. The frontend's existing
"overperforms" threshold (badge color, notification panel, sidebar badge
count) is ``overperform_ratio >= OVERPERFORM_RATIO_DEFAULT`` (2.0x by
default, configurable via env var) — that's exactly the "crossed a
benchmark" behaviour requested for the dashboard.

This module never talks to the database directly (easier to unit-test) — it
takes plain video rows in, returns updated ones out; the caller
(scrapers/*.py) is responsible for persisting the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class BaselineInput:
    """The minimum a video needs to participate in baseline math."""

    id: str
    format: str
    published_at: date
    views: int


@dataclass
class BaselineResult:
    id: str
    avg_views_baseline: float | None
    overperform_ratio: float | None


def compute_baselines(
    videos: list[BaselineInput],
    *,
    window: int = 10,
    min_videos: int = 3,
) -> list[BaselineResult]:
    """
    Compute a trailing per-(channel implied by caller, format) baseline for
    every video in ``videos``. Callers should pass in *all* of one channel's
    videos (across all formats) — this function buckets by ``format``
    itself so long-form/short/reel baselines never mix.
    """
    results: list[BaselineResult] = []

    by_format: dict[str, list[BaselineInput]] = {}
    for v in videos:
        by_format.setdefault(v.format, []).append(v)

    for _, group in by_format.items():
        ordered = sorted(group, key=lambda v: (v.published_at, v.id))
        window_views: list[int] = []
        for v in ordered:
            if len(window_views) >= min_videos:
                trailing = window_views[-window:]
                baseline = sum(trailing) / len(trailing)
                ratio = (v.views / baseline) if baseline > 0 else None
                results.append(BaselineResult(id=v.id, avg_views_baseline=baseline, overperform_ratio=ratio))
            else:
                results.append(BaselineResult(id=v.id, avg_views_baseline=None, overperform_ratio=None))
            window_views.append(v.views)

    return results


def is_overperforming(ratio: float | None, threshold: float) -> bool:
    return ratio is not None and ratio >= threshold


def recompute_and_store_channel_baselines(db: "Session", channel_id: str, settings) -> None:
    """
    Shared by both scrapers (app/scrapers/youtube.py, app/scrapers/
    instagram.py): reload every video the DB has for one channel, recompute
    baselines/ratios with compute_baselines(), and write the results back
    onto the ORM objects (caller is responsible for committing).
    """
    from app.models import Video  # local import: keeps this module DB-import-free for pure unit tests

    videos = db.query(Video).filter(Video.channel_id == channel_id).all()
    inputs = [BaselineInput(id=v.id, format=v.format, published_at=v.published_at, views=v.views) for v in videos]
    results = {
        r.id: r
        for r in compute_baselines(
            inputs,
            window=settings.baseline_window_videos,
            min_videos=settings.baseline_min_videos,
        )
    }
    for v in videos:
        r = results.get(v.id)
        v.avg_views_baseline = r.avg_views_baseline if r else None
        v.overperform_ratio = r.overperform_ratio if r else None
