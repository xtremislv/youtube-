def test_system_status_empty_state(client):
    body = client.get("/api/system/status").json()
    assert body["totalChannels"] == 0
    assert body["totalVideos"] == 0
    assert body["overperformCount"] == 0
    assert body["youtubeQuotaUsedToday"] == 0
    assert body["youtubeQuotaPct"] == 0.0
    assert body["lastScrapeStatus"] is None


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
