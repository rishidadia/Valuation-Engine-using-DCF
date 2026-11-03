"""Database engine + session management.

DATABASE_URL:
  PostgreSQL : postgresql+psycopg2://user:pass@host:5432/dcf_labs
  SQLite     : sqlite:///./dcf_labs.db   (default for local development)
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import settings

engine: Engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(Engine, "connect")
    def _sqlite_pragma(dbapi_connection, _):  # pragma: no cover
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from ..models.orm import Base
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
