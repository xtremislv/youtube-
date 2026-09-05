"""
Centralised app configuration.

Everything the app needs to know that varies between "my laptop", "CI", and
"production" lives here and nowhere else — no module should read
``os.environ`` directly. Values come from environment variables (a ``.env``
file in the ``backend/`` directory is auto-loaded for local development; in
production you set real environment variables on your host instead of
shipping a .env file).

See ``.env.example`` for what every setting means and how to obtain it.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://dashboard:dashboard@localhost:5432/dashboard"

    # YouTube Data API v3
    youtube_api_key: str = ""

    # Apify (Instagram)
    apify_api_token: str = ""
    apify_instagram_actor_id: str = "apify/instagram-scraper"
    apify_max_posts_per_channel: int = 30

    # Scrape trigger auth
    scrape_trigger_api_key: str = ""

    # Overperformance methodology
    overperform_ratio_default: float = 2.0
    baseline_window_videos: int = 10
    baseline_min_videos: int = 3

    # CORS — comma separated origins
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    # Misc / branding
    workspace_name: str = "Consumer Tech Competitors"

    # Internal scheduler (APScheduler). Leave off on scale-to-zero hosts.
    enable_internal_scheduler: bool = False
    daily_scrape_hour: int = 6
    daily_scrape_minute: int = 0

    # Cooldown (seconds) for the dashboard's unauthenticated "Refresh now"
    # button — see routers/scrape.py's POST /run-manual docstring.
    manual_scrape_cooldown_seconds: int = 300

    # YouTube's own daily quota ceiling (used only to render the "API Quota"
    # widget as a percentage — does not enforce anything).
    youtube_daily_quota_budget: int = 10_000

    # SponsorBlock (https://wiki.sponsor.ajay.app/w/API_Docs) — a free,
    # crowdsourced, YouTube-only database of sponsor/self-promo segments
    # inside videos, used to flag which competitor videos are running a
    # sponsorship so much so it needs no API key. See app/sponsorblock.py.
    sponsorblock_enabled: bool = True
    sponsorblock_api_base: str = "https://sponsor.ajay.app"
    # Segment categories counted as "sponsored" for the dashboard's badge/
    # filter — see the full category list in app/sponsorblock.py's docstring.
    sponsorblock_categories: str = "sponsor,selfpromo,exclusive_access"
    # Re-querying SponsorBlock for a video we already checked recently just
    # burns their free API for no benefit most of the time, so a video is
    # only re-checked once this many hours have passed since its last check
    # (segments do get submitted after a video's been out a while, so it's
    # not a one-and-done check — just throttled).
    sponsorblock_recheck_hours: int = 24
    # Caps how many videos get a fresh SponsorBlock lookup in one YouTube
    # scrape run (shared across every channel in that run, not per channel)
    # — protects against a big backfill making hundreds of sequential HTTP
    # calls and blowing the GitHub Actions job's --max-time or SponsorBlock's
    # rate limit. Whatever doesn't fit this run gets picked up on the next
    # one (there are several scheduled runs per day — see
    # .github/workflows/daily-scrape.yml), newest videos first.
    sponsorblock_max_checks_per_scrape: int = 40

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sponsorblock_category_list(self) -> list[str]:
        return [c.strip() for c in self.sponsorblock_categories.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings are cheap but re-parsing .env on every request is silly."""
    return Settings()
