"""
Tests for app/sponsorblock.py, split the same way the module is:
- parse_segments(): pure function, no network, no DB.
- SponsorBlockClient: real HTTP-shaped tests via respx (no real network).
- check_and_store_sponsor_segments(): DB-level tests using a fake client
  object, so budget/staleness/platform-filtering logic is verified without
  needing either a live SponsorBlock server or in-process HTTP mocking.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from app.config import Settings
from app.models import Channel, Video
from app.sponsorblock import (
    SponsorBlockClient,
    SponsorBlockRateLimited,
    SponsorCheckBudget,
    check_and_store_sponsor_segments,
    parse_segments,
)

# ── parse_segments ───────────────────────────────────────────────────────────


def test_parse_segments_sums_counted_categories_only():
    raw = [
        {"category": "sponsor", "segment": [10.0, 40.0]},  # 30s, counted
        {"category": "intro", "segment": [0.0, 10.0]},  # not counted
        {"category": "selfpromo", "segment": [100.0, 115.5]},  # 15.5s, counted
    ]
    summary = parse_segments(raw, {"sponsor", "selfpromo", "exclusive_access"})
    assert summary.has_sponsor is True
    assert summary.sponsor_seconds == 45.5


def test_parse_segments_no_matching_segments():
    raw = [{"category": "intro", "segment": [0.0, 5.0]}, {"category": "outro", "segment": [100.0, 110.0]}]
    summary = parse_segments(raw, {"sponsor", "selfpromo", "exclusive_access"})
    assert summary.has_sponsor is False
    assert summary.sponsor_seconds == 0.0


def test_parse_segments_empty_list():
    summary = parse_segments([], {"sponsor"})
    assert summary.has_sponsor is False
    assert summary.sponsor_seconds == 0.0


def test_parse_segments_ignores_zero_or_negative_length_segment():
    # Malformed/degenerate segment (end <= start) shouldn't add negative or
    # zero duration, and shouldn't be mistaken for "has a sponsor segment".
    raw = [{"category": "sponsor", "segment": [50.0, 50.0]}]
    summary = parse_segments(raw, {"sponsor"})
    assert summary.has_sponsor is False
    assert summary.sponsor_seconds == 0.0


# ── SponsorBlockClient ───────────────────────────────────────────────────────


@respx.mock
def test_client_returns_segments_on_200():
    respx.get("https://sponsor.ajay.app/api/skipSegments").mock(
        return_value=httpx.Response(200, json=[{"category": "sponsor", "segment": [1.0, 2.0]}])
    )
    client = SponsorBlockClient("https://sponsor.ajay.app")
    result = client.get_segments("abc123", ["sponsor"])
    assert result == [{"category": "sponsor", "segment": [1.0, 2.0]}]


@respx.mock
def test_client_returns_empty_list_on_404():
    respx.get("https://sponsor.ajay.app/api/skipSegments").mock(return_value=httpx.Response(404))
    client = SponsorBlockClient("https://sponsor.ajay.app")
    assert client.get_segments("no-data-video", ["sponsor"]) == []


@respx.mock
def test_client_raises_on_429():
    respx.get("https://sponsor.ajay.app/api/skipSegments").mock(return_value=httpx.Response(429))
    client = SponsorBlockClient("https://sponsor.ajay.app")
    with pytest.raises(SponsorBlockRateLimited):
        client.get_segments("abc123", ["sponsor"])


@respx.mock
def test_client_treats_network_error_as_no_data_not_a_crash():
    respx.get("https://sponsor.ajay.app/api/skipSegments").mock(side_effect=httpx.ConnectError("boom"))
    client = SponsorBlockClient("https://sponsor.ajay.app")
    assert client.get_segments("abc123", ["sponsor"]) == []


@respx.mock
def test_client_treats_server_error_as_no_data():
    respx.get("https://sponsor.ajay.app/api/skipSegments").mock(return_value=httpx.Response(500))
    client = SponsorBlockClient("https://sponsor.ajay.app")
    assert client.get_segments("abc123", ["sponsor"]) == []


# ── check_and_store_sponsor_segments ─────────────────────────────────────────


class FakeSponsorBlockClient:
    """Returns canned segments per video id, and counts calls made."""

    def __init__(self, segments_by_video: dict[str, list[dict]]):
        self.segments_by_video = segments_by_video
        self.calls: list[str] = []

    def get_segments(self, youtube_video_id: str, categories: list[str]) -> list[dict]:
        self.calls.append(youtube_video_id)
        return self.segments_by_video.get(youtube_video_id, [])


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        sponsorblock_categories="sponsor,selfpromo,exclusive_access",
        **overrides,
    )


def _video(id_, channel_id="youtube:c1", platform="youtube", checked_at=None):
    return Video(
        id=id_, channel_id=channel_id, platform=platform, title=id_, views=100,
        published_at=dt.date(2026, 8, 1), duration_seconds=300, format="long",
        sponsor_checked_at=checked_at,
    )


def test_marks_video_with_sponsor_segment(db_session):
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1"))
    db_session.commit()

    fake = FakeSponsorBlockClient({"v1": [{"category": "sponsor", "segment": [0.0, 30.0]}]})
    checked = check_and_store_sponsor_segments(db_session, _settings(), ["youtube:v1"], SponsorCheckBudget(10), client=fake)

    assert checked == 1
    video = db_session.get(Video, "youtube:v1")
    assert video.has_sponsor_segment is True
    assert video.sponsor_segment_seconds == 30.0
    assert video.sponsor_checked_at is not None


def test_marks_video_with_no_sponsor_segment(db_session):
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1"))
    db_session.commit()

    fake = FakeSponsorBlockClient({})  # no segments for any video
    checked = check_and_store_sponsor_segments(db_session, _settings(), ["youtube:v1"], SponsorCheckBudget(10), client=fake)

    assert checked == 1
    video = db_session.get(Video, "youtube:v1")
    assert video.has_sponsor_segment is False
    assert video.sponsor_segment_seconds is None
    assert video.sponsor_checked_at is not None


def test_skips_recently_checked_video(db_session):
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1", checked_at=recent))
    db_session.commit()

    fake = FakeSponsorBlockClient({"v1": [{"category": "sponsor", "segment": [0.0, 10.0]}]})
    checked = check_and_store_sponsor_segments(
        db_session, _settings(sponsorblock_recheck_hours=24), ["youtube:v1"], SponsorCheckBudget(10), client=fake
    )

    assert checked == 0
    assert fake.calls == []
    video = db_session.get(Video, "youtube:v1")
    assert video.has_sponsor_segment is False  # untouched


def test_rechecks_stale_video(db_session):
    stale = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1", checked_at=stale))
    db_session.commit()

    fake = FakeSponsorBlockClient({"v1": [{"category": "sponsor", "segment": [0.0, 10.0]}]})
    checked = check_and_store_sponsor_segments(
        db_session, _settings(sponsorblock_recheck_hours=24), ["youtube:v1"], SponsorCheckBudget(10), client=fake
    )

    assert checked == 1
    assert db_session.get(Video, "youtube:v1").has_sponsor_segment is True


def test_naive_checked_at_from_sqlite_does_not_crash_comparison(db_session):
    """SQLite always hands back naive datetimes regardless of column type
    (see the identical concern in test_api_scrape.py) — this must not raise
    "can't compare offset-naive and offset-aware datetimes"."""
    naive_recent = dt.datetime.utcnow() - dt.timedelta(hours=1)
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1", checked_at=naive_recent))
    db_session.commit()

    fake = FakeSponsorBlockClient({})
    checked = check_and_store_sponsor_segments(db_session, _settings(), ["youtube:v1"], SponsorCheckBudget(10), client=fake)
    assert checked == 0  # recently checked (naive-but-recent), correctly skipped


def test_respects_shared_budget_across_videos(db_session):
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add_all([_video("youtube:v1"), _video("youtube:v2"), _video("youtube:v3")])
    db_session.commit()

    fake = FakeSponsorBlockClient({})
    budget = SponsorCheckBudget(2)
    checked = check_and_store_sponsor_segments(db_session, _settings(), ["youtube:v1", "youtube:v2", "youtube:v3"], budget, client=fake)

    assert checked == 2
    assert fake.calls == ["v1", "v2"]  # stopped before v3
    assert budget.remaining == 0
    assert db_session.get(Video, "youtube:v3").sponsor_checked_at is None  # never touched


def test_skips_instagram_videos(db_session):
    db_session.add(Channel(id="instagram:c1", platform="instagram", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("instagram:v1", channel_id="instagram:c1", platform="instagram"))
    db_session.commit()

    fake = FakeSponsorBlockClient({"v1": [{"category": "sponsor", "segment": [0.0, 10.0]}]})
    checked = check_and_store_sponsor_segments(db_session, _settings(), ["instagram:v1"], SponsorCheckBudget(10), client=fake)

    assert checked == 0
    assert fake.calls == []
    assert db_session.get(Video, "instagram:v1").has_sponsor_segment is False


def test_disabled_setting_short_circuits(db_session):
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add(_video("youtube:v1"))
    db_session.commit()

    fake = FakeSponsorBlockClient({"v1": [{"category": "sponsor", "segment": [0.0, 10.0]}]})
    checked = check_and_store_sponsor_segments(
        db_session, _settings(sponsorblock_enabled=False), ["youtube:v1"], SponsorCheckBudget(10), client=fake
    )
    assert checked == 0
    assert fake.calls == []


def test_stale_skip_does_not_consume_budget(db_session):
    """Regression test for a real bug: budget.take() used to run BEFORE the
    platform/staleness checks, so a video skipped for being already-checked-
    recently still burned a unit of the shared per-run budget. Since
    scrape_channel passes a channel's *entire* tracked history every run
    (not just newly-discovered videos), a channel with a big already-covered
    backlog could silently eat the whole run's budget walking past videos
    it already checked, starving every other channel's — and its own
    remaining unchecked videos' — share of real lookups. Budget must only
    be spent immediately before an actual network call."""
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add_all([_video("youtube:v1", checked_at=recent), _video("youtube:v2")])
    db_session.commit()

    fake = FakeSponsorBlockClient({"v2": [{"category": "sponsor", "segment": [0.0, 10.0]}]})
    budget = SponsorCheckBudget(1)
    checked = check_and_store_sponsor_segments(
        db_session, _settings(), ["youtube:v1", "youtube:v2"], budget, client=fake
    )

    assert checked == 1
    assert fake.calls == ["v2"]  # v1's stale-skip must not have cost the one unit v2 needed
    assert budget.remaining == 0
    assert db_session.get(Video, "youtube:v2").has_sponsor_segment is True


def test_rate_limit_stops_remaining_checks_this_call(db_session):
    class RateLimitedAfterOne:
        def __init__(self):
            self.calls: list[str] = []

        def get_segments(self, youtube_video_id, categories):
            self.calls.append(youtube_video_id)
            if youtube_video_id == "v2":
                raise SponsorBlockRateLimited("nope")
            return []

    db_session.add(Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    db_session.add_all([_video("youtube:v1"), _video("youtube:v2"), _video("youtube:v3")])
    db_session.commit()

    fake = RateLimitedAfterOne()
    checked = check_and_store_sponsor_segments(
        db_session, _settings(), ["youtube:v1", "youtube:v2", "youtube:v3"], SponsorCheckBudget(10), client=fake
    )

    assert checked == 1  # only v1 completed; v2's rate-limit stopped the loop before v3
    assert fake.calls == ["v1", "v2"]
    assert db_session.get(Video, "youtube:v3").sponsor_checked_at is None
