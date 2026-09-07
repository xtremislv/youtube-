"""
API-level tests for /api/search — GET /latest (the page-reload path, never
touches YouTube) and POST /topic (a fresh search; cooldown- and
budget-guarded). Real YouTube calls are never exercised here — POST /topic
tests monkeypatch app.topic_search.run_topic_search, matching
test_api_scrape.py's pattern for /check-velocity.
"""

import datetime as dt

from app.models import ScrapeRun
from app.topic_search import CandidateVideo, ResolvedChannel, TopicSearchOutcome, _persist_outcome


def _fake_outcome(query="iphone review", quota=122):
    candidate = CandidateVideo(
        video_external_id="abc123",
        title="iPhone Ultra Review",
        thumbnail_url="https://img.example/abc123.jpg",
        video_url="https://www.youtube.com/watch?v=abc123",
        views=2_000_000,
        published_at=dt.date(2026, 9, 1),
        channel_external_id="UCxyz",
        channel_name="mkbhd",
        channel_handle=None,
        channel_avatar_url="https://img.example/mkbhd.jpg",
        subscriber_count=19_000_000,
    )
    return TopicSearchOutcome(
        query=query,
        searched_at=dt.datetime.now(dt.timezone.utc),
        lookback_days=60,
        min_subscribers=500_000,
        region_code="IN",
        top_n=10,
        total_candidates=23,
        outperform_count=1,
        youtube_quota_units_used=quota,
        channels=[
            ResolvedChannel(
                rank=1,
                candidate=candidate,
                score=0.1,
                channel_median_views=1_000_000,
                overperform_ratio=2.0,
                is_outperforming=True,
            )
        ],
    )


def _install_fake_search(monkeypatch, db_session, *, outcome=None, error=None):
    import app.topic_search as topic_search_module

    def _fake(db, settings, query):
        if error is not None:
            raise error
        result = outcome or _fake_outcome(query=query)
        _persist_outcome(db, result)
        return result

    monkeypatch.setattr(topic_search_module, "run_topic_search", _fake)


# ── GET /api/search/latest ───────────────────────────────────────────────────


def test_get_latest_returns_null_when_no_search_yet(client):
    resp = client.get("/api/search/latest")
    assert resp.status_code == 200
    assert resp.json() is None


def test_get_latest_never_calls_youtube(client, test_settings):
    # No youtube_api_key configured at all (conftest.py) — if this endpoint
    # tried to talk to YouTube it would raise; getting a clean 200/null back
    # instead proves it's DB-only.
    assert test_settings.youtube_api_key == ""
    resp = client.get("/api/search/latest")
    assert resp.status_code == 200


# ── POST /api/search/topic — validation ─────────────────────────────────────


def test_search_topic_rejects_empty_query(client, test_settings):
    test_settings.youtube_api_key = "fake-key"
    resp = client.post("/api/search/topic", json={"query": "   "})
    assert resp.status_code == 400


def test_search_topic_requires_youtube_api_key_configured(client):
    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 503
    assert "YOUTUBE_API_KEY" in resp.json()["detail"]


# ── POST /api/search/topic — success path ───────────────────────────────────


def test_search_topic_success_returns_expected_shape(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session)

    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "iphone review"
    assert body["totalCandidates"] == 23
    assert body["outperformCount"] == 1
    assert body["regionCode"] == "IN"
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["rank"] == 1
    assert ch["channelName"] == "mkbhd"
    assert ch["subscriberCount"] == 19_000_000
    assert ch["videoId"] == "abc123"
    assert ch["isOutperforming"] is True
    assert ch["overperformRatio"] == 2.0


def test_search_topic_records_a_scrape_run_for_quota_accounting(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session)

    client.post("/api/search/topic", json={"query": "iphone review"})
    run = db_session.query(ScrapeRun).filter(ScrapeRun.platform == "youtube_search").one()
    assert run.status == "success"
    assert run.youtube_quota_units_used == 122


def test_search_topic_result_is_readable_via_latest_afterward(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session)

    client.post("/api/search/topic", json={"query": "iphone review"})
    latest = client.get("/api/search/latest")
    assert latest.status_code == 200
    assert latest.json()["query"] == "iphone review"
    assert latest.json()["channels"][0]["channelName"] == "mkbhd"


def test_search_topic_overwrites_previous_search_not_accumulates(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"

    _install_fake_search(monkeypatch, db_session, outcome=_fake_outcome(query="first topic"))
    client.post("/api/search/topic", json={"query": "first topic"})

    # Cooldown would otherwise block back-to-back searches — simulate it
    # having elapsed by backdating the cache row directly.
    from app.models import TopicSearchCache

    cache = db_session.get(TopicSearchCache, 1)
    cache.searched_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        seconds=test_settings.topic_search_cooldown_seconds + 1
    )
    db_session.commit()

    _install_fake_search(monkeypatch, db_session, outcome=_fake_outcome(query="second topic"))
    resp = client.post("/api/search/topic", json={"query": "second topic"})
    assert resp.status_code == 200, resp.text

    latest = client.get("/api/search/latest").json()
    assert latest["query"] == "second topic"
    # Exactly one query's worth of channel rows ever exists — not 2.
    from app.models import TopicSearchCacheChannel

    assert db_session.query(TopicSearchCacheChannel).count() == 1


# ── POST /api/search/topic — cooldown ────────────────────────────────────────


def test_search_topic_blocked_within_cooldown(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session)

    first = client.post("/api/search/topic", json={"query": "iphone review"})
    assert first.status_code == 200

    second = client.post("/api/search/topic", json={"query": "another topic"})
    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_search_topic_allowed_once_cooldown_elapses(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session)
    client.post("/api/search/topic", json={"query": "iphone review"})

    from app.models import TopicSearchCache

    cache = db_session.get(TopicSearchCache, 1)
    cache.searched_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        seconds=test_settings.topic_search_cooldown_seconds + 1
    )
    db_session.commit()

    resp = client.post("/api/search/topic", json={"query": "another topic"})
    assert resp.status_code == 200, resp.text


# ── POST /api/search/topic — daily quota budget guard ───────────────────────


def test_search_topic_blocked_when_daily_budget_would_be_exceeded(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    test_settings.youtube_daily_quota_budget = 100
    _install_fake_search(monkeypatch, db_session)

    # Already spent 50/100 today via the regular scraper — this search's
    # ~122-unit estimate would blow well past the remaining 50.
    db_session.add(
        ScrapeRun(platform="youtube", started_at=dt.datetime.utcnow(), status="success", youtube_quota_units_used=50)
    )
    db_session.commit()

    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 429
    assert "quota" in resp.json()["detail"].lower()


def test_search_topic_allowed_when_budget_is_sufficient(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    test_settings.youtube_daily_quota_budget = 10_000
    _install_fake_search(monkeypatch, db_session)

    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 200, resp.text


# ── POST /api/search/topic — failure handling ───────────────────────────────


def test_search_topic_surfaces_a_clear_502_on_failure(client, db_session, test_settings, monkeypatch):
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session, error=RuntimeError("simulated YouTube API failure"))

    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 502
    assert "simulated YouTube API failure" in resp.json()["detail"]

    run = db_session.query(ScrapeRun).filter(ScrapeRun.platform == "youtube_search").one()
    assert run.status == "failed"


def test_search_topic_failure_does_not_block_next_attempt_via_cooldown(client, db_session, test_settings, monkeypatch):
    # A failed search shouldn't leave a cache row behind (nothing was ever
    # persisted), so the cooldown — keyed off the cache's searched_at —
    # should not kick in for the very next request.
    test_settings.youtube_api_key = "fake-key"
    _install_fake_search(monkeypatch, db_session, error=RuntimeError("boom"))
    client.post("/api/search/topic", json={"query": "iphone review"})

    _install_fake_search(monkeypatch, db_session)
    resp = client.post("/api/search/topic", json={"query": "iphone review"})
    assert resp.status_code == 200, resp.text


# ── /api/system/status — must not be confused by youtube_search runs ───────


def test_system_status_excludes_search_runs_from_last_scrape(client, db_session):
    db_session.add(ScrapeRun(platform="youtube", started_at=dt.datetime(2026, 9, 1), status="success"))
    db_session.add(
        ScrapeRun(platform="youtube_search", started_at=dt.datetime(2026, 9, 7), status="success", youtube_quota_units_used=122)
    )
    db_session.commit()

    resp = client.get("/api/system/status")
    body = resp.json()
    assert body["lastScrapeStatus"] == "success"
    # lastScrapeStartedAt should be the youtube run (Sep 1), not the later
    # youtube_search run (Sep 7) — a search is not a "scrape".
    assert body["lastScrapeStartedAt"].startswith("2026-09-01")


def test_system_status_quota_includes_search_spend(client, db_session):
    db_session.add(ScrapeRun(platform="youtube", started_at=dt.datetime.utcnow(), status="success", youtube_quota_units_used=50))
    db_session.add(
        ScrapeRun(platform="youtube_search", started_at=dt.datetime.utcnow(), status="success", youtube_quota_units_used=122)
    )
    db_session.commit()

    resp = client.get("/api/system/status")
    assert resp.json()["youtubeQuotaUsedToday"] == 172
