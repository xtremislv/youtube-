"""
Parse the ISO 8601 duration strings YouTube's API returns (e.g. ``"PT12M34S"``,
``"PT1H2M3S"``, ``"PT45S"``) into whole seconds.

Written by hand instead of pulling in the ``isodate`` dependency — YouTube
only ever emits the small subset of ISO 8601 durations that fit hours,
minutes and seconds, so a ~10-line regex covers 100% of real responses.
"""

from __future__ import annotations

import re

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration(value: str) -> int:
    """
    '' -> 0
    'PT45S' -> 45
    'PT12M34S' -> 754
    'PT1H2M3S' -> 3723
    'P0D' -> 0
    Malformed input -> 0 (never raises; a video with an unparsable duration
    should not crash a whole scrape run).
    """
    if not value:
        return 0
    match = _ISO8601_DURATION_RE.match(value.strip())
    if not match:
        return 0
    parts = match.groupdict()
    days = int(parts["days"] or 0)
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


# YouTube widened "Shorts" eligibility to videos of up to 3 minutes in 2024.
# A video at or under this length is classified as "short"; longer is "long".
YOUTUBE_SHORT_MAX_SECONDS = 180


def classify_youtube_format(duration_seconds: int) -> str:
    return "short" if duration_seconds <= YOUTUBE_SHORT_MAX_SECONDS else "long"
