import datetime as dt

from app.models import Channel, Video


def test_system_status_empty_state(client):
    body = client.get("/api/system/status").json()
    assert body["totalChannels"] == 0
    assert body["totalVideos"] == 0
    assert body["overperformCount"] == 0
    assert body["youtubeQuotaUsedToday"] == 0
    assert body["youtubeQuotaPct"] == 0.0
    assert body["lastScrapeStatus"] is None


def test_system_status_overperform_count_uses_median_not_average(client, db_session):
    """The sidebar badge / notification bell should agree with the
    Overperformance page's default metric (median — see filters.metric in
    src/App.tsx), not silently fall back to the average baseline."""
    channel = Channel(id="youtube:c1", platform="youtube", external_id="c1", handle="c1", name="Channel One", avatar_initials="C1")
    db_session.add(channel)
    db_session.add_all(
        [
            # Overperforms on average (2.05) but NOT on median (1.8) — if the
            # count used the average column this would wrongly count as 1.
            Video(
                id="v1", channel_id="youtube:c1", platform="youtube", title="V1", views=1000,
                published_at=dt.date(2026, 8, 1), duration_seconds=60, format="long",
                overperform_ratio=2.05, overperform_ratio_median=1.8,
            ),
            # Overperforms on median (2.5) but not on average (1.5).
            Video(
                id="v2", channel_id="youtube:c1", platform="youtube", title="V2", views=1000,
                published_at=dt.date(2026, 8, 2), duration_seconds=60, format="long",
                overperform_ratio=1.5, overperform_ratio_median=2.5,
            ),
        ]
    )
    db_session.commit()

    body = client.get("/api/system/status").json()
    assert body["overperformCount"] == 1  # only v2 clears the default 2.0x threshold on median


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
