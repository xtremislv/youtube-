"""
API-level tests for /api/channels. No real YouTube/Apify calls happen here
— test_settings (conftest.py) leaves both API keys blank, so channel
creation exercises only the "create the row, skip live identity
resolution" path. That path is exactly what a fresh clone with no API keys
configured yet will hit, so it's worth covering on its own.
"""


def test_create_and_list_youtube_channel(client):
    resp = client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd", "cohort": "Tech Giants"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "youtube:@mkbhd"
    assert body["platform"] == "youtube"
    assert body["handle"] == "mkbhd"
    assert body["cohort"] == "Tech Giants"
    assert body["subs"] == "—"  # no live resolution without an API key

    listed = client.get("/api/channels").json()
    assert len(listed) == 1
    assert listed[0]["id"] == "youtube:@mkbhd"


def test_create_instagram_channel_normalizes_handle(client):
    resp = client.post("/api/channels", json={"platform": "instagram", "handle": "@theverge/"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "instagram:theverge"


def test_duplicate_channel_rejected(client):
    client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"})
    resp = client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"})
    assert resp.status_code == 409


def test_invalid_platform_rejected(client):
    resp = client.post("/api/channels", json={"platform": "tiktok", "handle": "someone"})
    assert resp.status_code == 422


def test_filter_channels_by_platform(client):
    client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"})
    client.post("/api/channels", json={"platform": "instagram", "handle": "theverge"})
    yt_only = client.get("/api/channels", params={"platform": "youtube"}).json()
    assert len(yt_only) == 1
    assert yt_only[0]["platform"] == "youtube"


def test_patch_channel_cohort_and_deactivate(client):
    created = client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"}).json()
    patched = client.patch(f"/api/channels/{created['id']}", json={"cohort": "Camera Labs", "is_active": False})
    assert patched.status_code == 200
    assert patched.json()["cohort"] == "Camera Labs"
    assert patched.json()["isActive"] is False
    # inactive channels are hidden from the default listing
    assert client.get("/api/channels").json() == []
    assert len(client.get("/api/channels", params={"include_inactive": True}).json()) == 1


def test_delete_channel(client):
    created = client.post("/api/channels", json={"platform": "youtube", "handle": "@mkbhd"}).json()
    resp = client.delete(f"/api/channels/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/api/channels").json() == []
    assert client.delete(f"/api/channels/{created['id']}").status_code == 404


def test_cohorts_endpoint_reflects_real_channels(client):
    client.post("/api/channels", json={"platform": "youtube", "handle": "@a", "cohort": "Tech Giants"})
    client.post("/api/channels", json={"platform": "youtube", "handle": "@b", "cohort": "Tech Giants"})
    client.post("/api/channels", json={"platform": "instagram", "handle": "c", "cohort": "Camera Labs"})
    client.post("/api/channels", json={"platform": "instagram", "handle": "d"})  # no cohort

    cohorts = {c["label"]: c["count"] for c in client.get("/api/channels/cohorts").json()}
    assert cohorts == {"Tech Giants": 2, "Camera Labs": 1}
