"""
Same idea as test_youtube_parsing.py: feed normalize_instagram_item /
parse_profile_meta realistic Apify dataset-item shapes (based on the
commonly-used apify/instagram-scraper field names documented in its Actor
README) and check the normalized output — no Apify token, no network.

If you switch to a different Apify actor, update SAMPLE_REEL/SAMPLE_PHOTO
below to match its real output (copy one item from the actor's dataset in
the Apify console) and re-run this file — a passing suite is your signal
that app/scrapers/instagram.py's field-name aliases still match.
"""

import datetime as dt

from app.scrapers.instagram import normalize_instagram_item, parse_profile_meta

SAMPLE_REEL = {
    "id": "3123456789012345678",
    "shortCode": "Cxxxxxxxxxx",
    "type": "Video",
    "caption": "Shot on Pixel 9 Pro — Tokyo Trip\n#pixel9pro #tokyo",
    "url": "https://www.instagram.com/p/Cxxxxxxxxxx/",
    "displayUrl": "https://scontent.example.com/thumb.jpg",
    "videoUrl": "https://scontent.example.com/video.mp4",
    "videoDuration": 30.5,
    "videoPlayCount": 4_200_000,
    "likesCount": 312_000,
    "commentsCount": 8_400,
    "timestamp": "2026-08-16T09:00:00.000Z",
    "ownerFullName": "MKBHD Photos",
    "ownerUsername": "mkbhd_photos",
    "followersCount": 3_400_000,
}

SAMPLE_PHOTO_POST = {
    "id": "3123456789012399999",
    "shortCode": "Cyyyyyyyyyy",
    "type": "Image",
    "caption": "New desk setup",
    "url": "https://www.instagram.com/p/Cyyyyyyyyyy/",
    "displayUrl": "https://scontent.example.com/photo.jpg",
    "likesCount": 50_000,
    "commentsCount": 900,
    "timestamp": "2026-08-10T09:00:00.000Z",
}


def test_normalize_instagram_reel():
    parsed = normalize_instagram_item(SAMPLE_REEL, channel_id="instagram:mkbhd_photos")
    assert parsed is not None
    assert parsed["id"] == "instagram:3123456789012345678"
    assert parsed["channel_id"] == "instagram:mkbhd_photos"
    assert parsed["platform"] == "instagram"
    assert parsed["title"] == "Shot on Pixel 9 Pro — Tokyo Trip"
    assert parsed["thumbnail_url"] == "https://scontent.example.com/thumb.jpg"
    assert parsed["external_url"] == "https://www.instagram.com/p/Cxxxxxxxxxx/"
    assert parsed["views"] == 4_200_000
    assert parsed["likes"] == 312_000
    assert parsed["comments"] == 8_400
    assert parsed["published_at"] == dt.date(2026, 8, 16)
    assert parsed["duration_seconds"] == 30
    assert parsed["format"] == "reel"


def test_normalize_instagram_skips_photo_posts():
    # A plain photo carousel has no "views" metric worth tracking.
    assert normalize_instagram_item(SAMPLE_PHOTO_POST, channel_id="instagram:mkbhd_photos") is None


def test_normalize_instagram_missing_id_returns_none():
    assert normalize_instagram_item({"type": "Video", "videoPlayCount": 100}, channel_id="c1") is None


def test_normalize_instagram_accepts_alternate_field_names():
    # Some actor versions use pk/playCount/likes/comments/takenAt instead.
    raw = {
        "pk": "999",
        "productType": "clips",
        "text": "Alt schema reel",
        "playCount": 1_000_000,
        "likes": 50_000,
        "comments": 1_200,
        "takenAt": 1755331200,  # 2025-08-16T09:20:00Z as a unix timestamp
        "thumbnailUrl": "https://scontent.example.com/alt-thumb.jpg",
    }
    parsed = normalize_instagram_item(raw, channel_id="instagram:someone")
    assert parsed is not None
    assert parsed["id"] == "instagram:999"
    assert parsed["views"] == 1_000_000
    assert parsed["likes"] == 50_000
    assert parsed["comments"] == 1_200
    assert parsed["thumbnail_url"] == "https://scontent.example.com/alt-thumb.jpg"


def test_parse_profile_meta():
    meta = parse_profile_meta([SAMPLE_REEL])
    assert meta["name"] == "MKBHD Photos"
    assert meta["avatar_initials"] == "MP"
    assert meta["subscriber_count"] == 3_400_000


def test_parse_profile_meta_empty_items():
    assert parse_profile_meta([]) == {}
