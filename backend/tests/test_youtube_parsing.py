"""
Feeds parse_channel_resource / parse_video_resource realistic (hand-shaped
to match Google's documented response schema) YouTube Data API v3 JSON — no
network, no API key needed. This is the part of the YouTube integration
that's actually worth testing without live credentials: given a correctly-
shaped API response, does the app extract the right fields?
"""

import datetime as dt

from app.scrapers.duration import parse_iso8601_duration
from app.scrapers.youtube import parse_channel_resource, parse_video_resource, resolve_channel_input

SAMPLE_CHANNEL = {
    "id": "UCBJycsmduvYEL83R_U4JriQ",
    "snippet": {
        "title": "Marques Brownlee",
        "thumbnails": {
            "default": {"url": "https://yt3.example.com/default.jpg"},
            "medium": {"url": "https://yt3.example.com/medium.jpg"},
            "high": {"url": "https://yt3.example.com/high.jpg"},
        },
    },
    "statistics": {"subscriberCount": "18200000", "hiddenSubscriberCount": False},
    "contentDetails": {"relatedPlaylists": {"uploads": "UUBJycsmduvYEL83R_U4JriQ"}},
}

SAMPLE_VIDEO = {
    "id": "dQw4w9WgXcQ",
    "snippet": {
        "title": "iPhone 17 Pro — 3 Weeks Later",
        "publishedAt": "2026-08-14T15:00:00Z",
        "thumbnails": {
            "default": {"url": "https://i.ytimg.com/default.jpg"},
            "medium": {"url": "https://i.ytimg.com/medium.jpg"},
            "high": {"url": "https://i.ytimg.com/high.jpg"},
        },
    },
    "statistics": {"viewCount": "8420000", "likeCount": "312000", "commentCount": "18400"},
    "contentDetails": {"duration": "PT12M34S"},
}

SAMPLE_SHORT = {
    "id": "abc123short",
    "snippet": {
        "title": "Galaxy Z Fold 7 Drop Test #Shorts",
        "publishedAt": "2026-08-25T10:00:00Z",
        "thumbnails": {"high": {"url": "https://i.ytimg.com/high.jpg"}},
    },
    "statistics": {"viewCount": "12400000", "likeCount": "540000", "commentCount": "31000"},
    "contentDetails": {"duration": "PT58S"},
}


def test_parse_channel_resource():
    parsed = parse_channel_resource(SAMPLE_CHANNEL)
    assert parsed["external_id"] == "UCBJycsmduvYEL83R_U4JriQ"
    assert parsed["name"] == "Marques Brownlee"
    assert parsed["avatar_url"] == "https://yt3.example.com/high.jpg"
    assert parsed["avatar_initials"] == "MB"
    assert parsed["subscriber_count"] == 18_200_000
    assert parsed["uploads_playlist_id"] == "UUBJycsmduvYEL83R_U4JriQ"


def test_parse_channel_resource_hidden_subscriber_count():
    raw = {**SAMPLE_CHANNEL, "statistics": {"hiddenSubscriberCount": True, "subscriberCount": "0"}}
    parsed = parse_channel_resource(raw)
    assert parsed["subscriber_count"] is None


def test_parse_video_resource():
    parsed = parse_video_resource(SAMPLE_VIDEO, channel_id="youtube:UCBJycsmduvYEL83R_U4JriQ")
    assert parsed["id"] == "youtube:dQw4w9WgXcQ"
    assert parsed["channel_id"] == "youtube:UCBJycsmduvYEL83R_U4JriQ"
    assert parsed["platform"] == "youtube"
    assert parsed["title"] == "iPhone 17 Pro — 3 Weeks Later"
    assert parsed["thumbnail_url"] == "https://i.ytimg.com/high.jpg"
    assert parsed["external_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert parsed["views"] == 8_420_000
    assert parsed["likes"] == 312_000
    assert parsed["comments"] == 18_400
    assert parsed["published_at"] == dt.date(2026, 8, 14)
    # Full instant too, not just the date — needed for velocity tracking's
    # elapsed-hours-since-publish math (see Video.published_at_ts).
    assert parsed["published_at_ts"] == dt.datetime(2026, 8, 14, 15, 0, 0, tzinfo=dt.timezone.utc)
    assert parsed["duration_seconds"] == parse_iso8601_duration("PT12M34S")
    assert parsed["format"] == "long"


def test_parse_video_resource_classifies_short():
    parsed = parse_video_resource(SAMPLE_SHORT, channel_id="youtube:UCBJycsmduvYEL83R_U4JriQ")
    assert parsed["format"] == "short"
    assert parsed["duration_seconds"] == 58


def test_parse_video_resource_missing_optional_stats():
    raw = {**SAMPLE_VIDEO, "statistics": {"viewCount": "100"}}
    parsed = parse_video_resource(raw, channel_id="c1")
    assert parsed["views"] == 100
    assert parsed["likes"] is None
    assert parsed["comments"] is None


def test_resolve_channel_input_variants():
    assert resolve_channel_input("UCBJycsmduvYEL83R_U4JriQ") == ("UCBJycsmduvYEL83R_U4JriQ", None)
    assert resolve_channel_input("@mkbhd") == (None, "mkbhd")
    assert resolve_channel_input("mkbhd") == (None, "mkbhd")
    assert resolve_channel_input("https://www.youtube.com/@mkbhd") == (None, "mkbhd")
    assert resolve_channel_input("https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ") == (
        "UCBJycsmduvYEL83R_U4JriQ",
        None,
    )
