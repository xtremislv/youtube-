"""
app/db_lock.py — the advisory-lock helpers behind /api/scrape/run-manual's
and /api/search/topic's cooldown-race fixes.

Two kinds of coverage here:

- Always-run, against the SQLite test engine: confirms both helpers are the
  documented no-op there (matching the test suite's SQLite dialect), so the
  race-closing code paths in scrape.py/search.py don't blow up when the
  suite runs.
- Gated on a real local Postgres being reachable (same default DSN
  app/config.py ships, or TEST_DATABASE_URL if set): SQLite has no advisory
  locks, so the actual blocking/leak-proofing behavior can only be verified
  against Postgres — same reasoning backend/README.md gives for verifying
  Alembic migrations against real Postgres. Skips cleanly if nothing is
  listening, so this never breaks a normal SQLite-only dev/CI run; run it
  locally (or in any environment with a Postgres reachable at that DSN) for
  the real coverage.

The Postgres-gated tests specifically reproduce the bug this module's
current design was built to avoid: a session-scoped advisory lock taken and
released on the *caller's* ORM Session directly breaks the instant that
Session commits in between (SQLAlchemy hands its next statement a
different pooled connection, so the eventual "release" call silently does
nothing on a connection that never held the lock — leaking it forever).
``session_scoped_lock`` fixes this by holding the lock on its own dedicated
connection; these tests force exactly that connection churn and confirm
the lock still comes out clean.
"""

from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db_lock import LOCK_KEY_MANUAL_SCRAPE, LOCK_KEY_TOPIC_SEARCH, advisory_lock, session_scoped_lock

POSTGRES_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://dashboard:dashboard@localhost:5432/dashboard"
)


def _postgres_engine_or_skip(**engine_kwargs):
    engine = create_engine(POSTGRES_TEST_DSN, future=True, **engine_kwargs)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(f"no Postgres reachable at {POSTGRES_TEST_DSN!r} for db_lock's real-blocking tests")
    return engine


def test_advisory_lock_is_a_noop_on_sqlite(db_session) -> None:
    # db_session (conftest.py) is bound to the in-memory SQLite test engine.
    # Must not raise, and must not require SQLite to support anything
    # Postgres-specific.
    advisory_lock(db_session, LOCK_KEY_MANUAL_SCRAPE)
    advisory_lock(db_session, LOCK_KEY_MANUAL_SCRAPE)  # re-entrant no-op, too


def test_session_scoped_lock_is_a_noop_on_sqlite(db_session) -> None:
    with session_scoped_lock(db_session, LOCK_KEY_TOPIC_SEARCH):
        db_session.execute(text("SELECT 1"))


def test_session_scoped_lock_blocks_a_concurrent_holder() -> None:
    engine = _postgres_engine_or_skip(pool_size=3, max_overflow=2)
    Session = sessionmaker(bind=engine, future=True)
    key = 88_001
    holder = Session()
    waiter = Session()
    try:
        with session_scoped_lock(holder, key):
            acquired = threading.Event()

            def _try_acquire() -> None:
                with session_scoped_lock(waiter, key):
                    acquired.set()

            t = threading.Thread(target=_try_acquire, daemon=True)
            t.start()
            t.join(timeout=1.0)
            assert not acquired.is_set(), "waiter should still be blocked while holder holds the lock"

        # holder's `with` has exited -- the waiter's thread should now
        # complete promptly.
        t.join(timeout=5.0)
        assert acquired.is_set(), "waiter should acquire once the holder releases"
    finally:
        holder.close()
        waiter.close()
        engine.dispose()


def test_session_scoped_lock_survives_the_callers_connection_churning() -> None:
    """Regression test for the exact bug this module's design avoids: a
    small pool forces the protected session onto a *different* physical
    connection than the one it started on (via an intervening commit while
    another session grabs the freed connection first) -- session_scoped_lock
    must still release cleanly, because its own lock connection was never
    tied to the caller's in the first place."""
    engine = _postgres_engine_or_skip(pool_size=1, max_overflow=2)
    Session = sessionmaker(bind=engine, future=True)
    key = 88_002
    db = Session()
    inspector = Session()
    try:
        pid_before = db.execute(text("SELECT pg_backend_pid()")).scalar()

        with session_scoped_lock(db, key):
            rows = db.execute(
                text("SELECT pid FROM pg_locks WHERE locktype='advisory' AND objid=:key"), {"key": key}
            ).fetchall()
            assert rows and rows[0][0] != pid_before, "lock must live on its own connection, not db's"

            # Simulate search.py's multi-commit critical section: commit,
            # then let a concurrent session steal the freed connection so
            # db is forced onto a different one for its next statement.
            db.commit()
            thief = Session()
            pid_thief = thief.execute(text("SELECT pg_backend_pid()")).scalar()
            assert pid_thief == pid_before, "test setup: thief should have stolen db's freed connection"

            pid_after = db.execute(text("SELECT pg_backend_pid()")).scalar()
            assert pid_after != pid_before, "test setup: db should have churned onto a different connection"
            db.commit()
            thief.rollback()
            thief.close()

        # `with` has exited -- the lock must be fully released regardless of
        # db's connection churn above.
        remaining = inspector.execute(
            text("SELECT pid FROM pg_locks WHERE locktype='advisory' AND objid=:key"), {"key": key}
        ).fetchall()
        assert remaining == [], "lock leaked onto an orphaned connection"
    finally:
        db.close()
        inspector.close()
        engine.dispose()


def test_session_scoped_lock_releases_on_exception() -> None:
    engine = _postgres_engine_or_skip(pool_size=3, max_overflow=2)
    Session = sessionmaker(bind=engine, future=True)
    key = 88_003
    db = Session()
    inspector = Session()
    try:
        with pytest.raises(ValueError):
            with session_scoped_lock(db, key):
                raise ValueError("simulated failure mid-critical-section")
        remaining = inspector.execute(
            text("SELECT pid FROM pg_locks WHERE locktype='advisory' AND objid=:key"), {"key": key}
        ).fetchall()
        assert remaining == [], "lock must be released even when the protected block raises"
    finally:
        db.close()
        inspector.close()
        engine.dispose()
