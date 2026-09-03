"""
Auth behaviour for POST /api/scrape/run — the endpoint the GitHub Actions
cron workflow calls daily. Doesn't exercise real scraping (no API
keys/network in tests); just confirms the X-API-Key gate works, since a
regression there would mean anyone who finds the URL can burn your quota.
"""


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
