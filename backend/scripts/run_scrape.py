#!/usr/bin/env python
"""
Run a scrape from the command line — used by:
- you, manually, while testing ("did adding that channel actually work?")
- a VPS's own crontab/systemd timer, as an alternative to the HTTP trigger
  (see .github/workflows/daily-scrape.yml for the HTTP-trigger version used
  on hosts that sleep/scale to zero)

Usage:
    cd backend && source .venv/bin/activate
    python scripts/run_scrape.py                # both platforms
    python scripts/run_scrape.py --platform youtube
    python scripts/run_scrape.py --platform instagram

Exit code is non-zero if any platform run ended in "failed" status, so this
is safe to use directly as a cron job you'll get an email from on failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import SessionLocal
from app.scrape_service import run_daily_scrape


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["youtube", "instagram"], default=None)
    args = parser.parse_args()

    settings = get_settings()
    db = SessionLocal()
    had_failure = False
    try:
        runs = run_daily_scrape(db, settings, platform=args.platform)
        for run in runs:
            print(
                f"[{run.platform}] status={run.status} channels={run.channels_processed} "
                f"videos={run.videos_upserted} youtube_quota={run.youtube_quota_units_used} "
                f"apify_runs={run.apify_runs_started}"
            )
            if run.error_message:
                print(f"  errors: {run.error_message}")
            if run.status == "failed":
                had_failure = True
    finally:
        db.close()

    sys.exit(1 if had_failure else 0)


if __name__ == "__main__":
    main()
