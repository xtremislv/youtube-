"""Shared FastAPI dependencies: settings injection and the scrape-trigger auth check."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()


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
