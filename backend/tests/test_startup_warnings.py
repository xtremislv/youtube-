"""
app/main.py's _warn_about_missing_secrets — the startup-time check that
logs a clear warning for any of YOUTUBE_API_KEY / APIFY_API_TOKEN /
SCRAPE_TRIGGER_API_KEY left unset, so a forgotten secret shows up in a
deploy's boot logs immediately rather than only the first time something
tries to use it.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.main import _warn_about_missing_secrets


def _settings_with(**overrides) -> Settings:
    defaults = dict(
        database_url="sqlite:///:memory:",
        youtube_api_key="a-real-key",
        apify_api_token="a-real-token",
        scrape_trigger_api_key="a-real-secret",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_warns_when_youtube_api_key_missing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _warn_about_missing_secrets(_settings_with(youtube_api_key=""))
    assert any("YOUTUBE_API_KEY" in r.message for r in caplog.records)


def test_warns_when_apify_api_token_missing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _warn_about_missing_secrets(_settings_with(apify_api_token=""))
    assert any("APIFY_API_TOKEN" in r.message for r in caplog.records)


def test_warns_when_scrape_trigger_api_key_missing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _warn_about_missing_secrets(_settings_with(scrape_trigger_api_key=""))
    assert any("SCRAPE_TRIGGER_API_KEY" in r.message for r in caplog.records)


def test_no_warnings_when_everything_is_configured(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _warn_about_missing_secrets(_settings_with())
    assert caplog.records == []
