"""
Turning a caught exception into text that's safe to persist or hand back
over HTTP — used everywhere a scrape/search failure's message ends up in
``ScrapeRun.error_message`` (readable by anyone via the unauthenticated
``GET /api/scrape/runs``) or directly in an API error response (``POST
/api/search/topic`` and ``POST /api/scrape/run-manual`` have no API key —
see their routers' docstrings).

The specific hazard this closes: this app builds its YouTube client with
``build(..., developerKey=api_key)`` (see app/scrapers/youtube.py), and
google-api-python-client appends that key to every request as a plain
``key=...`` query parameter rather than a header. When a request fails,
the library's ``HttpError`` embeds the *full request URL* — API key
included — in both ``repr()`` and ``str()``. Before this module existed,
every ``except Exception as exc: ... f"{exc}"`` in the scrape/search paths
would happily put that URL (and the real ``YOUTUBE_API_KEY``) into a
database row or an HTTP response body that an unauthenticated caller can
read — trivially reachable by sending ``POST /api/search/topic`` a filter
that YouTube rejects (an invalid ``region``, for instance) and reading the
key straight out of the resulting 502.

``safe_error_message`` is the fix: build a message from ``HttpError``'s
status/reason only (never ``.uri``, which is exactly where the key lives),
and — as a backstop for any other library whose exceptions might embed a
credential-bearing URL — redact common credential-shaped query parameters
from whatever text remains.
"""

from __future__ import annotations

import re

try:
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover - always installed in practice; keeps this
    # module importable in a hypothetical stripped-down environment instead
    # of crashing every caller at import time.
    HttpError = None  # type: ignore[assignment,misc]

# Backstop redaction for anything not already handled by the HttpError case
# above: strips "key=...", "token=...", "api_key=...", "access_token=...",
# "secret=..." (case-insensitive) wherever they appear in a string, in case
# some other client (Apify's, httpx, a future dependency) ever embeds a
# credential-bearing URL in an exception's text.
_CREDENTIAL_QUERY_PARAM = re.compile(r"(?i)\b(key|token|api[_-]?key|access[_-]?token|secret)=[^&\s\"'<>]+")


def safe_error_message(exc: Exception) -> str:
    """A description of `exc` safe to store in ScrapeRun.error_message or
    return in an HTTP response — informative enough to diagnose (still
    reports the real HTTP status/reason for an API failure) without ever
    echoing back a secret that happened to be embedded in the failing
    request's URL."""
    if HttpError is not None and isinstance(exc, HttpError):
        status = getattr(exc, "status_code", None) or getattr(exc.resp, "status", "?")
        reason = (exc.reason or "").strip()
        return f"HTTP {status}: {reason}" if reason else f"HTTP {status}"
    return _CREDENTIAL_QUERY_PARAM.sub(r"\1=REDACTED", str(exc))
