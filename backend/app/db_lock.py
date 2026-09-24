"""
Cross-process critical-section helpers for the "check a cooldown, then act"
pattern used by POST /api/scrape/run-manual and POST /api/search/topic.

The bug this closes: both of those endpoints read some "when did this last
run" value, and only *afterward* — sometimes much afterward, since a topic
search's cooldown marker (TopicSearchCache.searched_at) isn't written until
the whole YouTube round trip finishes — write a new value recording that a
run has started. Two requests landing in that gap (a double-click, two
browser tabs, someone hitting the URL directly) can both read "no recent
run" before either has committed anything, so both proceed — the cooldown
that's supposed to cap how much quota/Apify credit repeated calls can burn
doesn't actually prevent two full runs for the price of one.

Two flavors, for two differently-shaped critical sections:

``advisory_lock(db, key)`` — transaction-scoped (``pg_advisory_xact_lock``),
taken directly on the caller's ``db: Session``. Automatically released the
moment ``db``'s *current* transaction ends (commit or rollback) — exactly
right when the critical section closes at or before the next commit, e.g.
scrape.py's manual-trigger race, which is settled as soon as the "running"
ScrapeRun row is inserted.

``session_scoped_lock(db, key)`` — a context manager wrapping
``pg_advisory_lock``/``pg_advisory_unlock``, for a critical section that
spans *multiple* commits on the caller's ORM Session (search.py's cooldown
check -> budget guard -> "running" ScrapeRun row -> long-running YouTube
call -> success/failure row, several `db.commit()` calls apart). It
deliberately does NOT take the lock on the caller's `db: Session`: a plain
ORM `Session.commit()` returns its underlying DBAPI connection to the
pool, and the Session's *next* statement can silently be handed back a
*different* physical connection (verified directly against Postgres: under
even mild concurrency — another request's Session grabbing the just-freed
connection first — this reliably happens). Since Postgres's session-level
advisory locks are scoped to the physical backend connection, not the ORM
Session object, acquiring on `db` and releasing on `db` later risks
releasing on a connection that never held the lock — `pg_advisory_unlock`
is a silent no-op in that case (no exception, just a `false` nobody
checks), leaking the lock on the original, now-idle-in-the-pool connection
until that specific connection happens to be evicted — which, since
nothing else ever touches it again, means indefinitely in practice. Every
subsequent call to this endpoint then blocks forever waiting for a lock
that will never be released: a self-inflicted permanent deadlock.
`session_scoped_lock` sidesteps all of this by checking out one dedicated
connection of its own — untouched by anything the caller's `db` does in
between — held for the entire `with` block, and explicitly unlocked *and
closed* afterward (closing a connection also drops every session-level
advisory lock it holds, so even a failed explicit unlock can't leak it
past that point).

Both are no-ops against any non-Postgres dialect/bind (the test suite's
SQLite) — SQLite has no equivalent, but the test suite runs single-threaded
(TestClient makes one call at a time), so the race either lock guards
against cannot occur there regardless.

Distinct integer keys per critical section keep unrelated call sites from
blocking on each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Arbitrary, just needs to be distinct per critical section and stable
# across deploys (picking a new number would only reopen the race for one
# release, not corrupt anything).
LOCK_KEY_MANUAL_SCRAPE = 72_701
LOCK_KEY_TOPIC_SEARCH = 72_702


def advisory_lock(db: Session, key: int) -> None:
    """Blocks (on Postgres) until any other transaction holding this same
    key commits or rolls back. Automatically released the moment ``db``'s
    *current* transaction ends (including by an unrelated ``db.commit()``
    elsewhere in the same request) — use this only when the critical section
    ends at or before the next commit. For a critical section that spans
    multiple commits (e.g. an early "started" row, then a much later
    "finished" row), use ``session_scoped_lock`` instead. No-op on any
    non-Postgres dialect."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


@contextmanager
def session_scoped_lock(db: Session, key: int) -> Iterator[None]:
    """Holds a Postgres session-level advisory lock for the duration of the
    ``with`` block, on a dedicated connection checked out from ``db``'s own
    engine (``db.get_bind()``) — deliberately separate from the connection(s)
    ``db`` itself uses for the actual work inside the block. See this
    module's docstring for why: the lock's connection identity must not be
    able to shift out from under it just because the caller's Session
    happened to commit.

    Takes ``db`` rather than an ``Engine`` directly — matching
    ``advisory_lock``'s signature — specifically so this respects the same
    ``app.dependency_overrides[get_db]`` swap the test suite already uses:
    deriving the engine from whatever ``db`` is actually bound to (the real
    Postgres engine in production, the in-memory SQLite engine in tests)
    means this never reaches past a test's override into a real database.

    Blocks indefinitely if another session already holds this key and never
    releases it (e.g. a crashed process) — the same unbounded-wait risk this
    codebase already accepts elsewhere, since no statement timeout is
    configured anywhere. No-op on any non-Postgres dialect/bind — safe to
    wrap unconditionally around code paths the SQLite test suite also runs.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return
    engine = bind if isinstance(bind, Engine) else bind.engine
    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            yield
        finally:
            # Best-effort explicit unlock — belt-and-suspenders alongside the
            # close() below, which is what actually guarantees release even
            # if this connection is already broken (a broken connection's
            # unlock would raise, but close() still drops the lock server-side).
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            except Exception:  # noqa: BLE001 — connection may already be dead;
                # closing it below still releases the lock at the Postgres level.
                pass
    finally:
        conn.close()
