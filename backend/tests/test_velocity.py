"""
Tests for app/velocity.py, split the same way the module is:
- compute_velocity_baselines(): pure function, no DB, no network.
- capture_velocity_snapshots(): DB-level tests using a fake YouTube client,
  mirroring test_sponsorblock.py's FakeSponsorBlockClient pattern.
"""

from __future__ import annotations

import datetime as dt
from datetime import timedelta

from app.config import Settings
from app.models import Channel, Video, VideoVelocitySnapshot
from app.velocity import (
    VelocityVideoInput,
    capture_velocity_snapshots,
    compute_velocity_baselines,
)

D0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def days(n: int) -> dt.datetime:
    return D0 + timedelta(days=n)


# ── compute_velocity_baselines ──────────────────────────────────────────────


def test_no_ratio_before_min_videos():
    videos = [
        VelocityVideoInput(id=f"v{i}", format="long", published_at=days(i), checkpoint_views={1: 1000})
        for i in range(3)
    ]
    results = {r.id: r for r in compute_velocity_baselines(videos, window=10, min_videos=3)}
    assert results["v0"].checkpoint_ratios == {}
    assert results["v1"].checkpoint_ratios == {}
    assert results["v2"].checkpoint_ratios == {}


def test_baseline_uses_trailing_window_per_checkpoint():
    videos = [
        VelocityVideoInput(id=f"v{i}", format="long", published_at=days(i), checkpoint_views={1: 1000})
        for i in range(4)
    ]
    videos.append(VelocityVideoInput(id="v4", format="long", published_at=days(4), checkpoint_views={1: 5000}))
    results = {r.id: r for r in compute_velocity_baselines(videos, window=10, min_videos=3)}
    assert results["v4"].checkpoint_ratios == {1: 5.0}


def test_missing_checkpoint_does_not_pollute_other_checkpoints_window():
    # v0-v2 only ever hit their 3h mark (never captured 1h); v3 hits both.
    # v3's 3h ratio should be built from v0-v2's 3h views (all 1000), giving
    # baseline 1000 -> ratio 5.0. Its 1h ratio should have no baseline at
    # all yet (only 0 prior videos have any 1h data), i.e. absent, not a
    # ratio computed against a wrongly-zero-padded window.
    videos = [
        VelocityVideoInput(id=f"v{i}", format="long", published_at=days(i), checkpoint_views={3: 1000})
        for i in range(3)
    ]
    videos.append(
        VelocityVideoInput(id="v3", format="long", published_at=days(3), checkpoint_views={1: 200, 3: 5000})
    )
    results = {r.id: r for r in compute_velocity_baselines(videos, window=10, min_videos=3)}
    assert results["v3"].checkpoint_ratios == {3: 5.0}
    assert 1 not in results["v3"].checkpoint_ratios


def test_formats_never_mix_velocity_baselines():
    long_videos = [
        VelocityVideoInput(id=f"long{i}", format="long", published_at=days(i), checkpoint_views={1: 10_000})
        for i in range(3)
    ]
    short_videos = [
        VelocityVideoInput(id=f"short{i}", format="short", published_at=days(i), checkpoint_views={1: 100})
        for i in range(3)
    ]
    long_videos.append(
        VelocityVideoInput(id="long3", format="long", published_at=days(10), checkpoint_views={1: 20_000})
    )
    results = {r.id: r for r in compute_velocity_baselines(long_videos + short_videos, window=10, min_videos=3)}
    assert results["long3"].checkpoint_ratios == {1: 2.0}  # 20000 / 10000, unaffected by the 100-view shorts


def test_zero_view_baseline_gives_no_ratio_not_a_crash():
    videos = [
        VelocityVideoInput(id=f"v{i}", format="long", published_at=days(i), checkpoint_views={1: 0})
        for i in range(4)
    ]
    results = {r.id: r for r in compute_velocity_baselines(videos, window=10, min_videos=3)}
    assert results["v3"].checkpoint_ratios == {}


# ── capture_velocity_snapshots ──────────────────────────────────────────────


class FakeYouTubeClient:
    """Returns canned videos.list-shaped resources per external video id,
    and records which ids were requested."""

    def __init__(self, videos_by_id: dict[str, dict]):
        self.videos_by_id = videos_by_id
        self.calls: list[str] = []

    def get_videos(self, video_ids: list[str]) -> list[dict]:
        self.calls.extend(video_ids)
        return [self.videos_by_id[v] for v in video_ids if v in self.videos_by_id]


def _raw(external_id: str, views: int, likes: int | None = None, comments: int | None = None) -> dict:
    stats = {"viewCount": str(views)}
    if likes is not None:
        stats["likeCount"] = str(likes)
    if comments is not None:
        stats["commentCount"] = str(comments)
    return {"id": external_id, "statistics": stats}


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        velocity_checkpoints_hours="1,3,6",
        velocity_checkpoint_grace_hours=2.0,
        **overrides,
    )


def _video(id_, *, channel_id="youtube:c1", published_at_ts=None, h1=None, h3=None, h6=None):
    return Video(
        id=id_,
        channel_id=channel_id,
        platform="youtube",
        title=id_,
        views=100,
        published_at=(published_at_ts.date() if published_at_ts else dt.date(2026, 8, 1)),
        published_at_ts=published_at_ts,
        duration_seconds=300,
        format="long",
        h1_views=h1,
        h3_views=h3,
        h6_views=h6,
    )


def _add_channel(db_session, id_="youtube:c1"):
    db_session.add(Channel(id=id_, platform="youtube", external_id=id_.removeprefix("youtube:"), handle=id_, name=id_, avatar_initials="C1"))


def test_captures_checkpoint_within_grace_window(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    published = now - dt.timedelta(hours=1.5)  # past the 1h mark, well within its 2h grace
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=published))
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 5000, likes=10, comments=2)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)
    db_session.commit()

    assert stats.videos_checked == 1
    assert stats.checkpoints_captured == 1  # only the 1h mark has been reached so far
    video = db_session.get(Video, "youtube:v1")
    assert video.h1_views == 5000
    assert video.h3_views is None
    assert video.velocity_checked_at is not None

    snapshot = db_session.query(VideoVelocitySnapshot).one()
    assert snapshot.checkpoint_hours == 1
    assert snapshot.views == 5000
    assert snapshot.likes == 10
    assert snapshot.comments == 2


def test_too_young_video_is_checked_but_captures_nothing_yet(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    published = now - dt.timedelta(hours=0.5)  # hasn't reached the 1h mark yet
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=published))
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 500)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)

    assert stats.videos_checked == 1  # still "open" (1h checkpoint not yet missed), so it's fetched
    assert stats.checkpoints_captured == 0
    assert db_session.get(Video, "youtube:v1").h1_views is None


def test_fully_resolved_video_is_never_queried(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    published = now - dt.timedelta(hours=2)
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=published, h1=100, h3=200, h6=300))
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 999)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)

    assert stats.videos_checked == 0
    assert fake.calls == []  # no open checkpoints left, so it's never even requested
    video = db_session.get(Video, "youtube:v1")
    assert video.h1_views == 100  # untouched


def test_video_past_every_grace_window_is_left_permanently_missed(db_session):
    # checkpoints=1,3,6 + grace=2 -> a video is only ever "open" up to 8h old.
    now = dt.datetime.now(dt.timezone.utc)
    published = now - dt.timedelta(hours=10)
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=published))
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 999)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)

    assert stats.videos_checked == 0
    assert fake.calls == []
    assert db_session.get(Video, "youtube:v1").h1_views is None  # missed, and stays missed


def test_missing_raw_video_skipped_without_crashing(db_session):
    # Simulates a video that's been deleted/privated on YouTube since it was
    # first tracked — videos.list simply won't return it.
    now = dt.datetime.now(dt.timezone.utc)
    published = now - dt.timedelta(hours=1.5)
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=published))
    db_session.commit()

    fake = FakeYouTubeClient({})  # nothing returned for any id
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)

    assert stats.videos_checked == 0
    assert stats.checkpoints_captured == 0
    video = db_session.get(Video, "youtube:v1")
    assert video.h1_views is None
    assert video.velocity_checked_at is None


def test_naive_published_at_ts_does_not_crash_comparison(db_session):
    """SQLite always hands back naive datetimes regardless of column type
    (see the identical concern in test_sponsorblock.py) — this must not
    raise "can't subtract offset-naive and offset-aware datetimes"."""
    naive_published = dt.datetime.utcnow() - dt.timedelta(hours=1.5)
    _add_channel(db_session)
    db_session.add(_video("youtube:v1", published_at_ts=naive_published))
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 5000)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)
    assert stats.videos_checked == 1
    assert stats.checkpoints_captured == 1


def test_recomputes_channel_baselines_after_capture(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    _add_channel(db_session)
    # Three older siblings already resolved at 1h = 1000 views each.
    for i in range(3):
        db_session.add(
            _video(f"youtube:old{i}", published_at_ts=now - dt.timedelta(hours=20), h1=1000, h3=1000, h6=1000)
        )
    # A brand-new upload that just crossed its 1h mark at 5x the baseline.
    db_session.add(_video("youtube:new", published_at_ts=now - dt.timedelta(hours=1.2)))
    db_session.commit()

    fake = FakeYouTubeClient({"new": _raw("new", 5000)})
    stats = capture_velocity_snapshots(db_session, _settings(baseline_window_videos=10, baseline_min_videos=3), client=fake)
    db_session.commit()

    assert stats.channels_recomputed == 1
    video = db_session.get(Video, "youtube:new")
    assert video.h1_views == 5000
    assert video.h1_ratio == 5.0


def test_instagram_videos_are_never_candidates(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(Channel(id="instagram:c1", platform="instagram", external_id="c1", handle="c1", name="C1", avatar_initials="C1"))
    ig_video = Video(
        id="instagram:v1", channel_id="instagram:c1", platform="instagram", title="v1", views=100,
        published_at=dt.date(2026, 8, 1), published_at_ts=now - dt.timedelta(hours=1.5),
        duration_seconds=30, format="reel",
    )
    db_session.add(ig_video)
    db_session.commit()

    fake = FakeYouTubeClient({"v1": _raw("v1", 5000)})
    stats = capture_velocity_snapshots(db_session, _settings(), client=fake)

    assert stats.videos_checked == 0
    assert fake.calls == []


def test_no_open_videos_returns_early_without_constructing_a_client(db_session):
    stats = capture_velocity_snapshots(db_session, _settings(), client=FakeYouTubeClient({}))
    assert stats.videos_checked == 0
    assert stats.checkpoints_captured == 0
    assert stats.channels_recomputed == 0
