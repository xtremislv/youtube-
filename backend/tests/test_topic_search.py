"""
Pure-function tests for app/topic_search.py — scoring, ranking/dedup, and
the channel-median comparison. No network, no DB (get_cached_search/
run_topic_search's DB-touching orchestration is covered at the API level in
test_api_search.py instead).
"""

import datetime as dt

from app.topic_search import (
    CandidateVideo,
    compute_median_performance,
    estimate_quota_cost,
    is_outperforming,
    score_candidate,
    select_top_channels,
)


def _candidate(channel_id, *, views, subs, days_ago, video_id=None):
    return CandidateVideo(
        video_external_id=video_id or f"vid-{channel_id}-{views}",
        title=f"Video from {channel_id}",
        thumbnail_url=None,
        video_url=f"https://www.youtube.com/watch?v={video_id or channel_id}",
        views=views,
        published_at=dt.date(2026, 9, 7) - dt.timedelta(days=days_ago),
        channel_external_id=channel_id,
        channel_name=channel_id,
        channel_handle=None,
        channel_avatar_url=None,
        subscriber_count=subs,
        uploads_playlist_id=f"UU{channel_id}",
    )


NOW = dt.date(2026, 9, 7)


# ── score_candidate ──────────────────────────────────────────────────────────


def test_score_candidate_basic_math():
    # 1,000,000 views / 500,000 subs / 2 days = 1.0
    assert score_candidate(views=1_000_000, subscriber_count=500_000, published_at=NOW - dt.timedelta(days=2), now=NOW) == 1.0


def test_score_candidate_floors_days_at_1_for_same_day_video():
    # Published "today" shouldn't divide by zero or explode — floored at 1 day.
    same_day = score_candidate(views=500_000, subscriber_count=500_000, published_at=NOW, now=NOW)
    assert same_day == 1.0


def test_score_candidate_zero_subscribers_is_zero_not_a_crash():
    assert score_candidate(views=1_000_000, subscriber_count=0, published_at=NOW, now=NOW) == 0.0


def test_score_candidate_older_video_scores_lower_for_same_daily_rate():
    # Same views, same subs, but a video 30 days old vs 3 days old — the
    # older one should score lower per the "views per day" normalization
    # (it's had more time to accumulate the same raw view count, i.e. it's
    # actually moving slower day-to-day), directly testing the age-weighting
    # nuance that was explicitly asked for.
    newer = score_candidate(views=3_000_000, subscriber_count=1_000_000, published_at=NOW - dt.timedelta(days=3), now=NOW)
    older = score_candidate(views=3_000_000, subscriber_count=1_000_000, published_at=NOW - dt.timedelta(days=30), now=NOW)
    assert newer > older


# ── select_top_channels ──────────────────────────────────────────────────────


def test_select_top_channels_gates_by_subscriber_threshold():
    candidates = [
        _candidate("big", views=1_000_000, subs=1_000_000, days_ago=1),
        _candidate("small", views=10_000_000, subs=100_000, days_ago=1),  # huge score but under the gate
    ]
    ranked, total = select_top_channels(candidates, min_subscribers=500_000, top_n=10, now=NOW)
    assert total == 1
    assert [r.candidate.channel_external_id for r in ranked] == ["big"]


def test_select_top_channels_dedupes_to_best_video_per_channel():
    candidates = [
        _candidate("chan-a", views=1_000_000, subs=1_000_000, days_ago=5, video_id="a1"),
        _candidate("chan-a", views=5_000_000, subs=1_000_000, days_ago=5, video_id="a2"),  # better score, same channel
    ]
    ranked, total = select_top_channels(candidates, min_subscribers=500_000, top_n=10, now=NOW)
    assert total == 2
    assert len(ranked) == 1
    assert ranked[0].candidate.video_external_id == "a2"


def test_select_top_channels_orders_by_score_descending_and_assigns_rank():
    candidates = [
        _candidate("low", views=500_000, subs=1_000_000, days_ago=10),
        _candidate("high", views=5_000_000, subs=1_000_000, days_ago=1),
    ]
    ranked, _ = select_top_channels(candidates, min_subscribers=500_000, top_n=10, now=NOW)
    assert [r.candidate.channel_external_id for r in ranked] == ["high", "low"]
    assert [r.rank for r in ranked] == [1, 2]


def test_select_top_channels_caps_at_top_n():
    candidates = [_candidate(f"chan-{i}", views=1_000_000, subs=1_000_000, days_ago=1) for i in range(15)]
    ranked, total = select_top_channels(candidates, min_subscribers=500_000, top_n=10, now=NOW)
    assert total == 15
    assert len(ranked) == 10


def test_select_top_channels_empty_input():
    ranked, total = select_top_channels([], min_subscribers=500_000, top_n=10, now=NOW)
    assert ranked == []
    assert total == 0


# ── compute_median_performance / is_outperforming ───────────────────────────


def test_compute_median_performance_basic():
    median, ratio = compute_median_performance(4_000_000, [1_000_000, 2_000_000, 3_000_000])
    assert median == 2_000_000
    assert ratio == 2.0


def test_compute_median_performance_no_history_returns_none():
    assert compute_median_performance(4_000_000, []) == (None, None)


def test_is_outperforming_threshold():
    assert is_outperforming(2.0, threshold=2.0) is True
    assert is_outperforming(1.9, threshold=2.0) is False
    assert is_outperforming(None, threshold=2.0) is False


# ── estimate_quota_cost ──────────────────────────────────────────────────────


def test_estimate_quota_cost_scales_with_top_n():
    class FakeSettings:
        search_top_n_channels = 10

    # 100 (search.list) + 1 (videos.list) + 1 (channels.list) + 10*2 (per-channel median lookups)
    assert estimate_quota_cost(FakeSettings()) == 122
