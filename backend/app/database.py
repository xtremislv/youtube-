"""
SQLAlchemy engine/session wiring.

One engine per process, one session per request. ``get_db`` is a FastAPI
dependency — every route that touches the database takes ``db: Session =
Depends(get_db)`` and never constructs a session itself, so tests can swap in
a different engine (see tests/conftest.py) without touching route code.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# pool_pre_ping=True: cheap health check on each checkout so a connection
# that a free-tier Postgres silently dropped (Neon autosuspends after 5 min
# idle) gets transparently replaced instead of surfacing as a 500.
# pool_recycle=1800: proactively retire any pooled connection older than 30
# minutes rather than waiting to discover it's dead — belt-and-suspenders
# alongside pool_pre_ping (which only catches an already-dead connection at
# checkout time) against a middlebox/load balancer between here and Neon
# silently closing a long-idle connection outside of Neon's own autosuspend.
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
