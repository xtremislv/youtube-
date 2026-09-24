"""Shared FastAPI dependencies: settings injection, the scrape-trigger auth
check, and the blanket per-IP rate limit."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.rate_limit import limiter


def settings_dep() -> Settings:
    return get_settings()


def _client_ip(request: Request) -> str:
    # Render (and most PaaS hosts) put the app behind a reverse proxy, so
    # request.client.host is often the proxy's own address rather than the
    # real caller's — prefer the first hop of X-Forwarded-For when present.
    # This is spoofable by the client itself if the proxy doesn't overwrite
    # it, which is a known, accepted limitation of IP-based limiting behind
    # an untrusted edge; it's still strictly better than one shared bucket
    # for every caller.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_dep(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    """Applied to every route (see app/main.py) except /healthz — a generic
    per-IP abuse backstop, see app/rate_limit.py's module docstring. Reads
    ``settings`` through the normal Depends(settings_dep) path specifically
    so the test suite's dependency override (tests/conftest.py) disables
    this the same way it swaps in test-only database/API-key settings,
    rather than needing its own separate test-detection mechanism."""
    if not settings.rate_limit_enabled or request.url.path == "/healthz":
        return
    allowed, retry_after = limiter.check(_client_ip(request), settings.rate_limit_requests_per_minute)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please slow down and try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )


def require_scrape_api_key(x_api_key: str | None = Header(default=None), settings: Settings = Depends(settings_dep)) -> None:
    """
    Guards POST /api/scrape/run. Anyone who can reach this endpoint can make
    your YouTube/Apify quota disappear, so it's protected by a shared
    secret (SCRAPE_TRIGGER_API_KEY) passed as the `X-API-Key` header —
    exactly what the GitHub Actions cron workflow and any manual `curl` send.
    """
    if not settings.scrape_trigger_api_key:
        # Fails closed: an unset secret should never mean "wide open".
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SCRAPE_TRIGGER_API_KEY is not configured on the server.",
        )
    if x_api_key != settings.scrape_trigger_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key header.")
