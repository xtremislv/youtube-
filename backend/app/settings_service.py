"""
Tiny persisted-settings helper around the single-row WorkspaceSettings table
(see app/models.py). Both app/routers/settings.py (the GET/PATCH the
sidebar's "Apify Usage" toggle calls) and app/scrape_service.py (which is
what actually enforces the toggle) import this rather than querying
WorkspaceSettings directly, so there's exactly one place that knows about
the get-or-create-the-singleton-row dance.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import WorkspaceSettings

_SETTINGS_ROW_ID = 1


def get_workspace_settings(db: Session) -> WorkspaceSettings:
    row = db.get(WorkspaceSettings, _SETTINGS_ROW_ID)
    if row is None:
        # First read ever (fresh DB, or upgrading from before this table
        # existed) — create the row with defaults (Instagram enabled) so
        # every caller can just read a row rather than handling None.
        row = WorkspaceSettings(id=_SETTINGS_ROW_ID)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def set_instagram_scraping_enabled(db: Session, enabled: bool) -> WorkspaceSettings:
    row = get_workspace_settings(db)
    row.instagram_scraping_enabled = enabled
    db.commit()
    db.refresh(row)
    return row
