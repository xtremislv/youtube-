"""
One place for the naive-vs-aware UTC datetime handling every scraper/router
module used to hand-roll separately.

Every timestamp column in app/models.py is declared ``DateTime(timezone=True)``,
but was populated with the naive ``dt.datetime.utcnow()`` — Postgres hands
back an aware datetime for such a column, while SQLite (used in tests)
always hands back a naive one, so any code that then does
``some_column_value - dt.datetime.now(dt.timezone.utc)`` needs to coerce
first or it crashes on one backend and passes silently on the other. That
"if naive, assume UTC" coercion had been copy-pasted into
app/routers/scrape.py, app/routers/search.py, app/sponsorblock.py, and
app/velocity.py, each with its own comment re-explaining the same trap.

``utcnow()`` replaces ``dt.datetime.utcnow()`` everywhere (fixing the
Python 3.12 deprecation of the latter for free, since this project's
Docker image pins ``python:3.12-slim``) and always returns an
aware-UTC value, so a value written through it never needs the coercion
in the first place. ``ensure_aware_utc()`` is for the read side — a value
that came back from the DB (or anywhere else) that might or might not
already be aware.
"""

from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    """The one call site for "the current time, as an aware UTC datetime" —
    use this instead of the deprecated, naive ``dt.datetime.utcnow()``."""
    return dt.datetime.now(dt.timezone.utc)


def ensure_aware_utc(value: dt.datetime) -> dt.datetime:
    """Returns ``value`` unchanged if it's already timezone-aware, otherwise
    assumes it's UTC (true for every naive datetime this codebase produces —
    see this module's docstring) and attaches that timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value
