"""
ORM models.

Four tables, deliberately kept small:

- ``Channel``  — a tracked YouTube channel or Instagram profile.
- ``Video``    — one scraped video/reel, always belonging to a Channel.
- ``ScrapeRun``— one audit-log row per scrape attempt (used for the sidebar
  "API Quota" widget and for debugging a failed daily run).
- ``WorkspaceSettings`` — a single-row table for dashboard-toggleable
  switches that need to persist and take effect immediately (as opposed to
  ``app/config.py``'s ``Settings``, which is env-var config fixed at deploy
  time). Currently just one switch: pausing Instagram (Apify) scraping.

Primary keys are human-readable strings of the form ``"<platform>:<external
id>"`` (e.g. ``"youtube:UC..."`` / ``"instagram:mkbhd"``) rather than opaque
UUIDs — it makes upserts idempotent (re-scraping the same channel/video
naturally updates the same row) and makes the database pleasant to read by
hand while debugging.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Channel(Base):
    __tablename__ = "channels"

    # "youtube:UCBJycsmduvYEL83R_U4JriQ" / "instagram:mkbhd"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # "youtube" | "instagram"
    external_id: Mapped[str] = mapped_column(String, nullable=False)  # channel id / IG username
    handle: Mapped[str] = mapped_column(String, nullable=False)  # @handle or username, as typed in
    name: Mapped[str] = mapped_column(String, nullable=False)  # display name
    avatar_initials: Mapped[str] = mapped_column(String(4), default="??")
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cohort: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    videos: Mapped[list["Video"]] = relationship(back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_channels_platform_external_id", "platform", "external_id", unique=True),)


class Video(Base):
    __tablename__ = "videos"

    # "youtube:dQw4w9WgXcQ" / "instagram:Cxxxxx"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)

    published_at: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)  # "short" | "long" | "reel"

    # Cached so /api/videos doesn't have to recompute a window function on
    # every request. Refreshed for the whole channel each scrape run — see
    # app/overperformance.py.
    avg_views_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    overperform_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    median_views_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    overperform_ratio_median: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)

    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    scraped_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    channel: Mapped["Channel"] = relationship(back_populates="videos")

    __table_args__ = (
        Index("ix_videos_channel_published", "channel_id", "published_at"),
        Index("ix_videos_platform_published", "platform", "published_at"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String, nullable=True)  # null = "whole platform" run

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|partial|failed

    channels_processed: Mapped[int] = mapped_column(Integer, default=0)
    videos_upserted: Mapped[int] = mapped_column(Integer, default=0)
    youtube_quota_units_used: Mapped[int] = mapped_column(Integer, default=0)
    apify_runs_started: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_scrape_runs_started_at", "started_at"),)


class WorkspaceSettings(Base):
    """Always exactly one row, with id=1 — see app/settings_service.py for
    the get-or-create helper every reader/writer goes through rather than
    querying this table directly."""

    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The sidebar's "Apify Usage" toggle. Enforced in app/scrape_service.py's
    # run_daily_scrape — the one function POST /api/scrape/run (the GitHub
    # Actions schedule), POST /api/scrape/run-manual (the dashboard's
    # "Refresh data" button), and the in-process scheduler all call — so
    # flipping this off stops Instagram/Apify runs from *any* trigger, not
    # just the dashboard button, without touching YouTube scraping.
    instagram_scraping_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )
