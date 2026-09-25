"""
Tests for the orchestration half of app/scrapers/youtube.py's scrape_channel
— specifically its resilience to one malformed video.list item in an
otherwise-normal batch (see the comment in scrape_channel's per-video loop).
Pure-function parsing tests for parse_channel_resource/parse_video_resource
live in test_youtube_parsing.py; this file uses a fake YouTubeClient-shaped
object, mirroring test_instagram_scraper.py's FakeApifyInstagramClient
pattern, so no real API key or network is needed.
"""

from __future__ import annotations

from app.config import Settings
from app.models import Channel, Video
from app.scrapers.youtube import scrape_channel


class FakeYouTubeClient:
    """Stands in for YouTubeClient: returns whatever the test configured,
    with no network call. Only implements the three methods scrape_channel
    actually calls."""

    def __init__(self, channel_resource: dict, video_resources: list[dict]):
        self._channel_resource = channel_resource
        self._video_resources = video_resources
        self.quota_units_used = 0

    def get_channel(self, *, channel_id: str | None = None, handle: str | None = None) -> dict | None:
        self.quota_units_used += 1
        return self._channel_resource

    def list_uploads_video_ids(self, uploads_playlist_id: str, *, max_pages: int) -> list[str]:
        self.quota_units_used += 1
        return [v["id"] for v in self._video_resources]

    def get_videos(self, video_ids: list[str]) -> list[dict]:
        self.quota_units_used += 1
        return [v for v in self._video_resources if v["id"] in video_ids]


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        youtube_api_key="",
        apify_api_token="",
        cors_origins="http://localhost:5173",
        sponsorblock_enabled=False,  # no network in this test
        baseline_window_videos=overrides.pop("baseline_window_videos", 3),
        baseline_min_videos=overrides.pop("baseline_min_videos", 1),
        **overrides,
    )


def _channel(db, handle: str = "@acct") -> Channel:
    channel = Channel(id=f"youtube:{handle}", platform="youtube", external_id=handle, handle=handle, name=handle, avatar_initials="AC")
    db.add(channel)
    db.flush()
    return channel


def _channel_resource(external_id: str = "UCabc123") -> dict:
    return {
        "id": external_id,
        "snippet": {"title": "Test Channel", "thumbnails": {}},
        "statistics": {"subscriberCount": "1000"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UUabc123"}},
    }


def _video_resource(video_id: str, *, views: int, day: int) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Video {video_id}",
            "publishedAt": f"2026-01-{day:02d}T09:00:00Z",
            "thumbnails": {},
        },
        "statistics": {"viewCount": str(views)},
        "contentDetails": {"duration": "PT5M"},
    }


def _video_resource_missing_published_at(video_id: str, *, views: int) -> dict:
    """Shaped like a real videos.list item but missing snippet.publishedAt —
    simulates the edge case parse_video_resource can't handle (it indexes
    that field directly rather than .get()-ing it)."""
    return {
        "id": video_id,
        "snippet": {"title": f"Video {video_id}", "thumbnails": {}},
        "statistics": {"viewCount": str(views)},
        "contentDetails": {"duration": "PT5M"},
    }


def test_scrape_channel_skips_one_malformed_video_without_losing_the_rest(db_session):
    """
    The scenario that motivated this fix: a batch of 3 videos where the
    middle one is missing snippet.publishedAt. Before the per-video
    try/except, parse_video_resource's KeyError would propagate out of
    scrape_channel entirely, and scrape_service.py's per-channel try/except
    would roll back *all three* upserts (and the channel's own resolved
    name/avatar) via db.rollback() — a single bad record costing the whole
    channel's scrape, not just itself.
    """
    channel = _channel(db_session)
    videos = [
        _video_resource("v1", views=100, day=1),
        _video_resource_missing_published_at("v2", views=200),
        _video_resource("v3", views=300, day=3),
    ]
    client = FakeYouTubeClient(_channel_resource(), videos)
    settings = _settings()

    stats = scrape_channel(client, db_session, channel, settings=settings)

    # The two well-formed videos still landed...
    assert db_session.get(Video, "youtube:v1") is not None
    assert db_session.get(Video, "youtube:v3") is not None
    assert db_session.get(Video, "youtube:v1").views == 100
    assert db_session.get(Video, "youtube:v3").views == 300
    # ...the malformed one was skipped, not silently dropped without a trace...
    assert db_session.get(Video, "youtube:v2") is None
    assert stats.videos_upserted == 2
    assert len(stats.errors) == 1
    assert "v2" in stats.errors[0]
    assert "unparseable" in stats.errors[0]
    # ...and nothing raised out of scrape_channel (the whole point — the
    # caller's per-channel try/except in scrape_service.py never even sees
    # an exception, so there's nothing to roll back).


def test_scrape_channel_all_videos_well_formed_no_errors(db_session):
    """Sanity check that the try/except doesn't change behavior for the
    normal (no malformed videos) case."""
    channel = _channel(db_session)
    videos = [_video_resource("v1", views=100, day=1), _video_resource("v2", views=200, day=2)]
    client = FakeYouTubeClient(_channel_resource(), videos)
    settings = _settings()

    stats = scrape_channel(client, db_session, channel, settings=settings)

    assert stats.videos_upserted == 2
    assert stats.errors == []
