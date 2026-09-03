"""
Pydantic (API) schemas.

These shapes are written to match ``src/App.tsx``'s ``Channel``/``Video``
TypeScript interfaces field-for-field (camelCase, same field names, same
formatted-string conventions like ``duration: "12:34"`` and
``subs: "18.2M"``) so the frontend needs no reshaping code — it can treat an
API response as if it were the old hardcoded mock array.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


def _camel(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(word.capitalize() for word in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)


# ── Channels ─────────────────────────────────────────────────────────────────


class ChannelOut(CamelModel):
    id: str
    name: str
    platform: str
    avatar: str = Field(validation_alias="avatar_initials", serialization_alias="avatar")
    avatar_url: str | None = None
    subs: str  # pre-formatted, e.g. "18.2M" — see app/formatting.py
    subscriber_count: int | None = None
    handle: str
    cohort: str | None = None
    is_active: bool


class ChannelCreate(BaseModel):
    """Body for POST /api/channels — how a new competitor gets tracked."""

    platform: str = Field(description='"youtube" or "instagram"')
    handle: str = Field(
        description=(
            "YouTube: a channel @handle (e.g. '@mkbhd'), a full channel URL, "
            "or a raw channel ID (UC...). Instagram: the username, with or "
            "without the leading @."
        )
    )
    cohort: str | None = Field(default=None, description="Optional group label, e.g. 'Tech Giants'.")


class ChannelUpdate(BaseModel):
    cohort: str | None = None
    is_active: bool | None = None
    notes: str | None = None


# ── Videos ───────────────────────────────────────────────────────────────────


class VideoOut(CamelModel):
    id: str
    channel_id: str
    channel_name: str = Field(validation_alias="channel.name", serialization_alias="channelName")
    platform: str
    title: str
    thumbnail: str | None = Field(default=None, validation_alias="thumbnail_url", serialization_alias="thumbnail")
    url: str | None = Field(default=None, validation_alias="external_url", serialization_alias="url")
    views: int
    avg_views: float | None = Field(default=None, validation_alias="avg_views_baseline", serialization_alias="avgViews")
    likes: int | None = None
    comments: int | None = None
    published_at: str = Field(serialization_alias="publishedAt")  # "YYYY-MM-DD" string, see formatting.py
    duration: str  # "MM:SS", see formatting.py
    format: str
    overperform_ratio: float | None = Field(default=None, serialization_alias="overperformRatio")

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True, arbitrary_types_allowed=True)


class VideoListResponse(BaseModel):
    videos: list[VideoOut]
    total: int
    overperform_count: int = Field(serialization_alias="overperformCount")

    model_config = ConfigDict(populate_by_name=True)


# ── System / scrape status ──────────────────────────────────────────────────


class SystemStatus(CamelModel):
    workspace_name: str
    youtube_quota_used_today: int
    youtube_quota_budget: int
    youtube_quota_pct: float
    last_scrape_started_at: dt.datetime | None = None
    last_scrape_status: str | None = None
    total_channels: int
    total_videos: int
    overperform_count: int


class ScrapeRunOut(CamelModel):
    id: int
    platform: str
    channel_id: str | None
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    channels_processed: int
    videos_upserted: int
    youtube_quota_units_used: int
    apify_runs_started: int
    error_message: str | None


class ScrapeTriggerResponse(BaseModel):
    message: str
    runs: list[ScrapeRunOut]


class CohortOut(BaseModel):
    label: str
    count: int
