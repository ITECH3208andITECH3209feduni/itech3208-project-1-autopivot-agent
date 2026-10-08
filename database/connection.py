"""Database engine and session configuration."""

from __future__ import annotations

import os
import warnings
from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session, sessionmaker

warnings.filterwarnings(
    "ignore",
    message=r".*does \*not\* support Decimal objects natively.*",
    category=SAWarning,
)

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_SQLITE_PATH = BASE_DIR / "autopivot.db"


def get_database_url() -> str:
    """The configured database URL, defaulting to a local SQLite file."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def is_sqlite(database_url: str | None = None) -> bool:
    return (database_url or get_database_url()).startswith("sqlite")


@lru_cache
def get_engine() -> Engine:
    database_url = get_database_url()

    if is_sqlite(database_url):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        return engine

    return create_engine(database_url, pool_pre_ping=True)


def get_db_session() -> Generator[Session, None, None]:
    session_factory = sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()

