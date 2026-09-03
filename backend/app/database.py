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
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
