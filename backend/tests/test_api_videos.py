"""
API-level tests for /api/videos: seeds channels + videos directly via the
ORM (bypassing the scrapers entirely — those are tested separately in
test_youtube_parsing.py / test_instagram_parsing.py) and checks that the
HTTP-level filtering/sorting/pagination matches the same rules the original
frontend mock implemented client-side (platform, multi-channel, date range,
views threshold, format — including "short" meaning short-or-reel — and the
four sort modes).
"""

import datetime as dt

from app.models import Channel, Video


def _channel(id_, platform="youtube", name="Channel"):
    return Channel(id=id_, platform=platform, external_id=id_, handle=id_, name=name, avatar_initials="CH")


def _video(
    id_,
    channel_id,
    *,
    platform="youtube",
    views=1000,
    published_at="2026-08-15",
    fmt="long",
    likes=10,
    comments=1,
    ratio=None,
    ratio_median=None,
):
    return Video(
        id=id_,
        channel_id=channel_id,
        platform=platform,
        title=f"Video {id_}",
        views=views,
        likes=likes,
        comments=comments,
        published_at=dt.date.fromisoformat(published_at),
        duration_seconds=600,
        format=fmt,
        overperform_ratio=ratio,
        avg_views_baseline=views / ratio if ratio else None,
        overperform_ratio_median=ratio_median,
        median_views_baseline=views / ratio_median if ratio_median else None,
    )


def _seed(db_session):
    c1 = _channel("youtube:c1", "youtube", "Channel One")
    c2 = _channel("instagram:c2", "instagram", "Channel Two")
    db_session.add_all([c1, c2])
    db_session.add_all(
        [
            # v1's median ratio (1.8) deliberately sits on the opposite side
            # of the 2.0x default threshold from its average ratio (2.05) —
            # exercises metric=average vs metric=median actually disagreeing
            # about whether a video counts as "overperforming".
            _video("v1", "youtube:c1", platform="youtube", views=8_000_000, published_at="2026-08-14", fmt="long", ratio=2.05, ratio_median=1.8),
            _video("v2", "youtube:c1", platform="youtube", views=12_000_000, published_at="2026-08-25", fmt="short", ratio=2.5, ratio_median=2.6),
            _video("v3", "instagram:c2", platform="instagram", views=500_000, published_at="2026-08-16", fmt="reel", ratio=1.2, ratio_median=0.9),
            _video("v4", "instagram:c2", platform="instagram", views=100_000, published_at="2026-07-01", fmt="reel", ratio=None, ratio_median=None),
        ]
    )
    db_session.commit()


def test_list_all_videos(client, db_session):
    _seed(db_session)
    resp = client.get("/api/videos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert len(body["videos"]) == 4


def test_filter_by_platform(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"platform": "instagram"}).json()
    assert body["total"] == 2
    assert all(v["platform"] == "instagram" for v in body["videos"])


def test_filter_by_channels(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"channels": ["youtube:c1"]}).json()
    assert body["total"] == 2
    assert all(v["channelId"] == "youtube:c1" for v in body["videos"])


def test_filter_by_date_range(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"date_from": "2026-08-01", "date_to": "2026-08-31"}).json()
    ids = {v["id"] for v in body["videos"]}
    assert ids == {"v1", "v2", "v3"}  # v4 published in July is excluded


def test_filter_by_views_threshold(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"views_threshold": 1_000_000}).json()
    ids = {v["id"] for v in body["videos"]}
    assert ids == {"v1", "v2"}


def test_format_short_includes_reels(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"format": "short"}).json()
    ids = {v["id"] for v in body["videos"]}
    assert ids == {"v2", "v3", "v4"}  # "short" format param means short-OR-reel


def test_format_reel_only(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"format": "reel"}).json()
    ids = {v["id"] for v in body["videos"]}
    assert ids == {"v3", "v4"}


def test_sort_by_views(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"sort_by": "views"}).json()
    views = [v["views"] for v in body["videos"]]
    assert views == sorted(views, reverse=True)


def test_sort_by_date(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"sort_by": "date"}).json()
    dates = [v["publishedAt"] for v in body["videos"]]
    assert dates == sorted(dates, reverse=True)


def test_sort_by_ratio_nulls_last(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"sort_by": "ratio"}).json()
    ratios = [v["overperformRatio"] for v in body["videos"]]
    assert ratios[-1] is None  # v4 has no baseline yet -> sorts last, not first
    non_null = [r for r in ratios if r is not None]
    assert non_null == sorted(non_null, reverse=True)


def test_overperform_count_uses_default_threshold(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos").json()
    # v1 (2.05) and v2 (2.5) are >= 2.0 default threshold; v3 (1.2) and v4 (None) are not
    assert body["overperformCount"] == 2


def test_overperform_count_respects_custom_threshold(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"overperform_ratio_threshold": 2.2}).json()
    assert body["overperformCount"] == 1  # only v2 (2.5) clears 2.2x


def test_every_video_always_includes_both_metrics(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos").json()
    v1 = next(v for v in body["videos"] if v["id"] == "v1")
    assert v1["overperformRatio"] == 2.05
    assert v1["overperformRatioMedian"] == 1.8
    assert v1["avgViews"] is not None
    assert v1["medianViews"] is not None


def test_metric_default_is_average(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos").json()
    # default threshold 2.0x: v1 (avg 2.05) and v2 (avg 2.5) clear it
    assert body["overperformCount"] == 2


def test_metric_median_changes_overperform_count_and_sort(client, db_session):
    _seed(db_session)
    body = client.get("/api/videos", params={"metric": "median"}).json()
    # median threshold 2.0x: only v2 (median 2.6) clears it — v1's median
    # (1.8) does not, unlike its average (2.05), proving the switch actually
    # changes which videos count as overperforming.
    assert body["overperformCount"] == 1

    sorted_body = client.get("/api/videos", params={"metric": "median", "sort_by": "ratio"}).json()
    ratios = [v["overperformRatioMedian"] for v in sorted_body["videos"]]
    assert ratios[-1] is None  # v4 still sorts last
    non_null = [r for r in ratios if r is not None]
    assert non_null == sorted(non_null, reverse=True)
    assert sorted_body["videos"][0]["id"] == "v2"  # highest median ratio (2.6) sorts first
