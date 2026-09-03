"""
Small, pure, heavily-tested string-formatting helpers.

Kept separate from the ORM/schema layer because these are the functions most
worth unit-testing in isolation (see tests/test_formatting.py) — they're
exactly the kind of "looks right until a 999,500-subscriber channel rounds
to 1.0M instead of 999.5K" bug that's cheap to catch with a test and
annoying to catch by eye.
"""

from __future__ import annotations


def format_count(n: int | None) -> str:
    """18_200_000 -> '18.2M', 890_000 -> '890K', 4_200 -> '4.2K', 950 -> '950'."""
    if n is None:
        return "—"
    n = int(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000_000:
        return f"{sign}{n / 1_000_000_000:.1f}B".replace(".0B", "B")
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{sign}{n / 1_000:.1f}K".replace(".0K", "K")
    return f"{sign}{n}"


def format_duration(seconds: int | None) -> str:
    """95 -> '1:35', 754 -> '12:34', 3725 -> '1:02:05', 45 -> '0:45'."""
    if not seconds or seconds < 0:
        seconds = 0
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def initials_from_name(name: str) -> str:
    """'Marques Brownlee' -> 'MB', 'linustech' -> 'LI', '' -> '??'."""
    words = [w for w in name.strip().split() if w]
    if not words:
        return "??"
    if len(words) == 1:
        word = words[0]
        return (word[:2] if len(word) >= 2 else (word + "?")).upper()
    return (words[0][0] + words[1][0]).upper()


def normalize_handle(handle: str, platform: str) -> str:
    """Strip whitespace/leading '@'/trailing slashes so stored handles are consistent."""
    h = handle.strip()
    if platform == "instagram":
        h = h.rstrip("/").split("/")[-1]  # tolerate a pasted profile URL
    h = h.lstrip("@")
    return h
