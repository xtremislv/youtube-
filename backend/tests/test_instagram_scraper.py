"""
Tests for the orchestration half of app/scrapers/instagram.py — the
two-call discover+refresh pattern in scrape_channel(), and the
_urls_needing_refresh() helper it's built on. (Pure-function parsing
tests for normalize_instagram_item()/parse_profile_meta() live in
test_instagram_parsing.py; this file uses a fake ApifyInstagramClient-
shaped object, mirroring test_velocity.py's/test_sponsorblock.py's fake-
client pattern, so no real Apify token or network is needed.)

The scenario every test here is built around: an Instagram account that
mixes photos in with its reels, so the actor's "most recent posts" window
(fetch_profile_posts) can easily stop covering a reel that's still inside
the overperformance baseline's trailing window (default: last 10 reels).
Without the second, targeted fetch_posts_by_url() call, that reel's view
count — and therefore the median/mean baseline computed from it — would
be silently frozen at a stale number forever.
"""

from __future__ import annotations

import datetime as dt

from app.config import Settings
from app.models import Channel, Video
from app.scrapers.instagram import _urls_needing_refresh, scrape_channel


class FakeApifyInstagramClient:
    """Stands in for ApifyInstagramClient: records what it was asked to
    fetch and returns whatever the test configured, with no network call."""

    def __init__(self, profile_items: list[dict], refresh_items: list[dict] | None = None, refresh_error: Exception | None = None):
        self.profile_items = profile_items
        self.refresh_items = refresh_items or []
        self.refresh_error = refresh_error
        self.refresh_calls: list[list[str]] = []
        self.runs_started = 0

    def fetch_profile_posts(self, username: str, *, max_posts: int) -> list[dict]:
        self.runs_started += 1
        return self.profile_items

    def fetch_posts_by_url(self, urls: list[str]) -> list[dict]:
        self.refresh_calls.append(list(urls))
        if self.refresh_error is not None:
            raise self.refresh_error
        self.runs_started += 1
        return self.refresh_items


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        youtube_api_key="",
        apify_api_token="",
        cors_origins="http://localhost:5173",
        baseline_window_videos=overrides.pop("baseline_window_videos", 3),
        baseline_min_videos=overrides.pop("baseline_min_videos", 1),
        **overrides,
    )


def _channel(db, handle: str = "acct") -> Channel:
    channel = Channel(
        id=f"instagram:{handle}", platform="instagram", external_id=handle, handle=handle, name=handle, avatar_initials="AC"
    )
    db.add(channel)
    db.flush()
    return channel


def _seed_reel(db, channel_id: str, *, post_id: str, day: int, views: int) -> Video:
    video = Video(
        id=f"instagram:{post_id}",
        channel_id=channel_id,
        platform="instagram",
        title=f"Reel {post_id}",
        external_url=f"https://www.instagram.com/p/{post_id}/",
        views=views,
        likes=10,
        comments=1,
        published_at=dt.date(2026, 1, day),
        duration_seconds=20,
        format="reel",
    )
    db.add(video)
    db.flush()
    return video


def _raw_reel(post_id: str, *, views: int, day: int) -> dict:
    return {
        "id": post_id,
        "shortCode": post_id,
        "type": "Video",
        "caption": f"Reel {post_id}",
        "url": f"https://www.instagram.com/p/{post_id}/",
        "displayUrl": "https://scontent.example.com/thumb.jpg",
        "videoDuration": 20.0,
        "videoPlayCount": views,
        "likesCount": 10,
        "commentsCount": 1,
        "timestamp": f"2026-01-{day:02d}T09:00:00.000Z",
    }


# ── _urls_needing_refresh ────────────────────────────────────────────────────


def test_urls_needing_refresh_excludes_discovered_and_respects_limit(db_session):
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=100)
    _seed_reel(db_session, channel.id, post_id="v2", day=2, views=100)
    _seed_reel(db_session, channel.id, post_id="v3", day=3, views=100)
    _seed_reel(db_session, channel.id, post_id="v4", day=4, views=100)

    urls = _urls_needing_refresh(db_session, channel.id, exclude_ids={"instagram:v4"}, limit=2)

    # Most recent first, v4 excluded (already covered by discovery this run).
    assert urls == [
        "https://www.instagram.com/p/v3/",
        "https://www.instagram.com/p/v2/",
    ]


def test_urls_needing_refresh_returns_fewer_when_channel_has_fewer_reels(db_session):
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=100)

    assert _urls_needing_refresh(db_session, channel.id, exclude_ids=set(), limit=5) == [
        "https://www.instagram.com/p/v1/"
    ]


def test_urls_needing_refresh_zero_limit_returns_nothing(db_session):
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=100)

    assert _urls_needing_refresh(db_session, channel.id, exclude_ids=set(), limit=0) == []


# ── scrape_channel: the two-call pattern ─────────────────────────────────────


def test_scrape_channel_refreshes_stale_reels_outside_discovery_window(db_session):
    """
    The scenario that motivated this fix: v2/v3/v4 are old enough that the
    actor's discovery call no longer returns them (simulating an account
    where photos pushed them out of the timeline window), but they're still
    inside the baseline_window_videos=3 trailing window the newest reel's
    baseline is computed from. Without the refresh call, v5's baseline
    would be computed from v2/v3/v4's stale 1000-view snapshots instead of
    their real, since-grown view counts.
    """
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=1000)
    _seed_reel(db_session, channel.id, post_id="v2", day=2, views=1000)
    _seed_reel(db_session, channel.id, post_id="v3", day=3, views=1000)
    _seed_reel(db_session, channel.id, post_id="v4", day=4, views=1000)

    # Discovery only surfaces the brand-new v5 — v1-v4 have aged out of the
    # actor's "most recent posts" window this run.
    profile_items = [_raw_reel("v5", views=500, day=5)]
    # The targeted refresh call reports that v2/v3/v4 have all grown to
    # 2000 views since they were first scraped.
    refresh_items = [
        _raw_reel("v4", views=2000, day=4),
        _raw_reel("v3", views=2000, day=3),
        _raw_reel("v2", views=2000, day=2),
    ]
    client = FakeApifyInstagramClient(profile_items, refresh_items)
    settings = _settings()

    stats = scrape_channel(client, db_session, channel, settings=settings)

    # Refresh was asked for exactly v4, v3, v2 (most-recent-first, v5 excluded
    # since discovery already covered it) — not v1, since window=3.
    assert client.refresh_calls == [
        [
            "https://www.instagram.com/p/v4/",
            "https://www.instagram.com/p/v3/",
            "https://www.instagram.com/p/v2/",
        ]
    ]

    assert db_session.get(Video, "instagram:v2").views == 2000
    assert db_session.get(Video, "instagram:v3").views == 2000
    assert db_session.get(Video, "instagram:v4").views == 2000
    assert db_session.get(Video, "instagram:v1").views == 1000  # outside the window, untouched — as expected

    # v5's baseline is computed from the now-fresh v2/v3/v4 views (2000 each),
    # not the stale 1000s they'd have kept without the refresh call.
    newest = db_session.get(Video, "instagram:v5")
    assert newest.avg_views_baseline == 2000.0
    assert newest.median_views_baseline == 2000.0
    assert newest.overperform_ratio_median == 0.25  # 500 / 2000

    assert stats.videos_upserted == 4  # 1 discovered + 3 refreshed
    assert stats.videos_refreshed == 3
    assert stats.errors == []


def test_scrape_channel_skips_refresh_call_when_discovery_already_covers_window(db_session):
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=1000)

    # baseline_window_videos=1 and discovery's own batch already includes
    # the one prior video needed — nothing left to refresh.
    profile_items = [_raw_reel("v1", views=1500, day=1), _raw_reel("v2", views=500, day=2)]
    client = FakeApifyInstagramClient(profile_items)
    settings = _settings(baseline_window_videos=1)

    stats = scrape_channel(client, db_session, channel, settings=settings)

    assert client.refresh_calls == []
    assert stats.videos_refreshed == 0
    assert db_session.get(Video, "instagram:v1").views == 1500


def test_scrape_channel_refresh_failure_keeps_discovery_batch_and_records_error(db_session):
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=1000)
    _seed_reel(db_session, channel.id, post_id="v2", day=2, views=1000)

    profile_items = [_raw_reel("v3", views=300, day=3)]
    client = FakeApifyInstagramClient(profile_items, refresh_error=RuntimeError("actor run failed"))
    settings = _settings(baseline_window_videos=2)

    stats = scrape_channel(client, db_session, channel, settings=settings)

    assert len(stats.errors) == 1
    assert "Apify refresh run failed" in stats.errors[0]
    # The discovery batch (the new v3) is still saved despite the refresh
    # call failing.
    assert db_session.get(Video, "instagram:v3") is not None
    assert db_session.get(Video, "instagram:v3").views == 300
    # v1/v2 simply stay at their last-known values rather than the run
    # crashing outright.
    assert db_session.get(Video, "instagram:v1").views == 1000
    assert db_session.get(Video, "instagram:v2").views == 1000
    assert stats.videos_refreshed == 0


def _raw_item_with_drifted_schema(post_id: str, *, day: int) -> dict:
    """Shaped like a real actor item enough to have an id and a "Video" type,
    but missing every view-count field name normalize_instagram_item knows
    about — simulating the actor output schema having renamed that field,
    per this module's docstring on why _first_present tries several aliases."""
    return {
        "id": post_id,
        "shortCode": post_id,
        "type": "Video",
        "caption": f"Reel {post_id}",
        "timestamp": f"2026-01-{day:02d}T09:00:00.000Z",
        # Deliberately no videoPlayCount/videoViewCount/playCount/viewCount.
    }


def test_scrape_channel_warns_when_discovery_items_all_fail_to_parse(db_session):
    """
    Every item the actor returned failed normalize_instagram_item (schema
    drift, not "this account posted nothing") — without a warning, this run
    would report status=success with videos_upserted=0, indistinguishable
    from a quiet day, even though backend/README.md's own troubleshooting
    section says a 0-upserted run with real actor results is exactly the
    "field names don't match this actor" case.
    """
    channel = _channel(db_session)
    profile_items = [_raw_item_with_drifted_schema("v1", day=1), _raw_item_with_drifted_schema("v2", day=2)]
    client = FakeApifyInstagramClient(profile_items)
    settings = _settings()

    stats = scrape_channel(client, db_session, channel, settings=settings)

    assert stats.videos_upserted == 0
    assert len(stats.errors) == 1
    assert "none were recognized as videos/reels" in stats.errors[0]
    assert "2 post(s)" in stats.errors[0]


def test_scrape_channel_warns_when_refresh_items_all_fail_to_parse(db_session):
    """Same schema-drift signal, but for the second (targeted refresh) call —
    the path responsible for keeping older tracked reels' views from going
    stale, so a silent failure here is easy to miss (new posts keep arriving
    fine while old ones quietly freeze)."""
    channel = _channel(db_session)
    _seed_reel(db_session, channel.id, post_id="v1", day=1, views=1000)
    _seed_reel(db_session, channel.id, post_id="v2", day=2, views=1000)

    profile_items = [_raw_reel("v3", views=300, day=3)]
    refresh_items = [_raw_item_with_drifted_schema("v2", day=2), _raw_item_with_drifted_schema("v1", day=1)]
    client = FakeApifyInstagramClient(profile_items, refresh_items)
    settings = _settings(baseline_window_videos=2)

    stats = scrape_channel(client, db_session, channel, settings=settings)

    assert stats.videos_refreshed == 0
    assert len(stats.errors) == 1
    assert "Apify refresh returned" in stats.errors[0]
    assert "none were recognized as videos/reels" in stats.errors[0]
    # The discovery batch's own new video is unaffected by the refresh call's
    # parse failures.
    assert db_session.get(Video, "instagram:v3").views == 300
