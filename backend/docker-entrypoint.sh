#!/usr/bin/env bash
# Runs before every container start: apply any pending Alembic migrations
# (a no-op if the DB is already current), then hand off to whatever CMD was
# given (uvicorn for the API; a scripts/*.py invocation for a one-off job
# container, e.g. `docker compose run --rm api python scripts/run_scrape.py`).
set -euo pipefail

echo "[entrypoint] Applying database migrations..."
alembic upgrade head

echo "[entrypoint] Starting: $*"
exec "$@"
