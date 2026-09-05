"""
Auth behaviour for POST /api/scrape/run — the endpoint the GitHub Actions
cron workflow calls daily. Doesn't exercise real scraping (no API
keys/network in tests); just confirms the X-API-Key gate works, since a
regression there would mean anyone who finds the URL can burn your quota.

Also covers POST /api/scrape/run-manual — the dashboard's "Refresh now"
button. It has no API key, so what's under test there is the cooldown
instead: a scrape that ran recently should block a second one, and one
that ran long enough ago (or never) should not.
"""

import datetime as dt

from app.models import ScrapeRun


def test_scrape_run_requires_api_key(client):
    resp = client.post("/api/scrape/run")
    assert resp.status_code == 401


def test_scrape_run_rejects_wrong_api_key(client):
    resp = client.post("/api/scrape/run", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_scrape_run_accepts_correct_api_key(client):
    # test_settings.scrape_trigger_api_key == "test-secret" (conftest.py).
    # Both API keys are blank in test settings, so each platform run records
    # a "failed" ScrapeRun with a clear "not configured" error rather than
    # attempting a real network call — that's the behavior under test here.
    resp = client.post("/api/scrape/run", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["runs"]) == 2
    statuses = {r["platform"]: r["status"] for r in body["runs"]}
    assert statuses == {"youtube": "success", "instagram": "success"}
    # "success" because there are zero active channels to fail on; add a
    # channel and it would report "failed" with a "not configured" error —
    # covered by test_scrape_run_reports_missing_keys_once_channels_exist.


def test_scrape_run_reports_missing_keys_once_channels_exist(client):
    client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"})
    resp = client.post("/api/scrape/run", params={"platform": "youtube"}, headers={"X-API-Key": "test-secret"})
    body = resp.json()
    run = body["runs"][0]
    assert run["status"] == "failed"
    assert "YOUTUBE_API_KEY" in run["errorMessage"]


def test_missing_server_secret_fails_closed(client, test_settings):
    test_settings.scrape_trigger_api_key = ""
    resp = client.post("/api/scrape/run", headers={"X-API-Key": "anything"})
    assert resp.status_code == 503


def test_manual_scrape_requires_no_api_key(client):
    # No X-API-Key header at all — this is the whole point of the endpoint.
    resp = client.post("/api/scrape/run-manual")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["runs"]) == 2


def test_manual_scrape_blocked_within_cooldown(client, db_session, test_settings):
    db_session.add(ScrapeRun(platform="youtube", started_at=dt.datetime.utcnow(), status="success"))
    db_session.commit()

    resp = client.post("/api/scrape/run-manual", params={"platform": "youtube"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert "Try again in" in resp.json()["detail"]


def test_manual_scrape_allowed_once_cooldown_elapses(client, db_session, test_settings):
    stale = dt.datetime.utcnow() - dt.timedelta(seconds=test_settings.manual_scrape_cooldown_seconds + 1)
    db_session.add(ScrapeRun(platform="youtube", started_at=stale, status="success"))
    db_session.commit()

    resp = client.post("/api/scrape/run-manual", params={"platform": "youtube"})
    assert resp.status_code == 200, resp.text


def test_manual_scrape_cooldown_is_scoped_per_platform(client, db_session):
    # A recent Instagram run shouldn't block a YouTube-only manual trigger.
    db_session.add(ScrapeRun(platform="instagram", started_at=dt.datetime.utcnow(), status="success"))
    db_session.commit()

    resp = client.post("/api/scrape/run-manual", params={"platform": "youtube"})
    assert resp.status_code == 200, resp.text


def test_manual_scrape_rejects_unknown_platform(client):
    resp = client.post("/api/scrape/run-manual", params={"platform": "tiktok"})
    assert resp.status_code == 400


def test_instagram_scraping_paused_by_sidebar_toggle_is_skipped_not_run(client):
    # The sidebar's "Apify Usage" toggle (PATCH /api/settings/scraper) — see
    # app/scrape_service.py's run_daily_scrape. Instagram should come back
    # "skipped" (no Apify call attempted) while YouTube runs as normal;
    # flipping it back on should resume Instagram immediately.
    client.patch("/api/settings/scraper", json={"instagram_scraping_enabled": False})

    resp = client.post("/api/scrape/run", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200, resp.text
    statuses = {r["platform"]: r["status"] for r in resp.json()["runs"]}
    assert statuses == {"youtube": "success", "instagram": "skipped"}

    ig_run = next(r for r in resp.json()["runs"] if r["platform"] == "instagram")
    assert ig_run["apifyRunsStarted"] == 0
    assert "paused" in ig_run["errorMessage"].lower()

    client.patch("/api/settings/scraper", json={"instagram_scraping_enabled": True})
    resumed = client.post("/api/scrape/run", headers={"X-API-Key": "test-secret"})
    statuses = {r["platform"]: r["status"] for r in resumed.json()["runs"]}
    assert statuses == {"youtube": "success", "instagram": "success"}


def test_instagram_paused_toggle_also_blocks_manual_refresh(client):
    client.patch("/api/settings/scraper", json={"instagram_scraping_enabled": False})
    resp = client.post("/api/scrape/run-manual", params={"platform": "instagram"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["runs"][0]["status"] == "skipped"


# ── POST /api/scrape/check-velocity — see app/velocity.py ───────────────────
# Same X-API-Key gate as /run (Depends(require_scrape_api_key)), so the auth
# behavior is identical; the extra case here is that it fails closed with a
# clear error when YOUTUBE_API_KEY itself isn't configured (this endpoint
# always needs to actually call YouTube, unlike /run which can at least
# record a "failed" ScrapeRun and return 200).


def test_check_velocity_requires_api_key(client):
    resp = client.post("/api/scrape/check-velocity")
    assert resp.status_code == 401


def test_check_velocity_rejects_wrong_api_key(client):
    resp = client.post("/api/scrape/check-velocity", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_check_velocity_fails_closed_without_server_secret(client, test_settings):
    test_settings.scrape_trigger_api_key = ""
    resp = client.post("/api/scrape/check-velocity", headers={"X-API-Key": "anything"})
    assert resp.status_code == 503


def test_check_velocity_requires_youtube_api_key_configured(client):
    # test_settings.youtube_api_key == "" (conftest.py) — no channels needed
    # to hit this; the endpoint should refuse before ever querying videos.
    resp = client.post("/api/scrape/check-velocity", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 503
    assert "YOUTUBE_API_KEY" in resp.json()["detail"]


def test_check_velocity_reports_zero_activity_with_no_open_videos(client, test_settings):
    test_settings.youtube_api_key = "fake-key-not-actually-called"
    resp = client.post("/api/scrape/check-velocity", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "message": "Checked 0 video(s), captured 0 checkpoint(s) across 0 channel(s).",
        "videosChecked": 0,
        "checkpointsCaptured": 0,
        "channelsRecomputed": 0,
    }


def test_check_velocity_surfaces_a_clear_502_on_failure(client, test_settings, monkeypatch):
    # Unlike /run (per-channel try/except, always 200 with a per-run
    # status), /check-velocity has no per-video isolation — a YouTube API
    # hiccup covers the whole batch. This should come back as a clean 502
    # with a readable message, not a bare 500 stack trace.
    import app.velocity as velocity_module

    def _boom(db, settings, client=None):
        raise RuntimeError("simulated YouTube API failure")

    monkeypatch.setattr(velocity_module, "capture_velocity_snapshots", _boom)
    test_settings.youtube_api_key = "fake-key"

    resp = client.post("/api/scrape/check-velocity", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 502
    assert "simulated YouTube API failure" in resp.json()["detail"]
