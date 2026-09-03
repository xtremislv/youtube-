#!/usr/bin/env python
"""
Bulk-add channels from a JSON file — this is the "give you the list of
channels later" workflow: drop your competitor list into a JSON file and
run this once (or re-run any time to add more; already-tracked channels are
skipped, not duplicated).

Usage:
    cd backend
    source .venv/bin/activate
    python scripts/seed_channels.py channels.seed.json

File format (see channels.seed.example.json):
[
  {"platform": "youtube", "handle": "@mkbhd", "cohort": "Tech Giants"},
  {"platform": "youtube", "handle": "@LinusTechTips", "cohort": "Tech Giants"},
  {"platform": "instagram", "handle": "theverge", "cohort": "Tech Giants"}
]

"handle" for YouTube accepts an @handle, a full channel URL, or a raw
channel ID (UC...). For Instagram it's just the username.
"cohort" is optional — it's the group label shown in the sidebar's "Saved
Cohorts" list (e.g. group your competitors into "Tech Giants" / "EDC & Desk"
/ "Camera Labs").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel_service import DuplicateChannelError, InvalidPlatformError, add_channel
from app.config import get_settings
from app.database import SessionLocal
from app.schemas import ChannelCreate


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <channels.json>")
        raise SystemExit(1)

    path = Path(sys.argv[1])
    entries = json.loads(path.read_text())
    settings = get_settings()
    db = SessionLocal()

    added, skipped, failed = 0, 0, 0
    try:
        for entry in entries:
            payload = ChannelCreate(**entry)
            try:
                channel = add_channel(db, settings, payload)
                print(f"  + added {channel.id} ({channel.name})")
                added += 1
            except DuplicateChannelError:
                print(f"  = already tracked, skipping: {entry['platform']} {entry['handle']}")
                skipped += 1
            except InvalidPlatformError as exc:
                print(f"  ! skipping invalid entry {entry}: {exc}")
                failed += 1
    finally:
        db.close()

    print(f"\nDone. added={added} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
