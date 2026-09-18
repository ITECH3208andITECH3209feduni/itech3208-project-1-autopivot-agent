"""Database engine and session configuration.

Two databases are supported and the URL decides which:

* **SQLite** (the default) — a single file, `autopivot.db`, in the project
  directory. Nothing to install, no server to start, no credentials. This is
  what a local development machine uses.
* **PostgreSQL** — set `DATABASE_URL` to a `postgresql+psycopg://...` URL and
  everything behaves exactly as it did before. Deployments and anyone already
  running a PostgreSQL instance are unaffected.

The schema is identical on both: `database/models.py` carries SQLite variants
for the two PostgreSQL-specific types it uses.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session, sessionmaker

# SQLite has no decimal type, so SQLAlchemy converts Numeric columns through
# float and warns each time it does. The three Numeric columns here are a price
# and two confidence scores between 0 and 1 — nothing where a float's last bit
# changes an outcome — and left unfiltered the warning buries the server log.
warnings.filterwarnings(
    "ignore",
    message=r".*does \*not\* support Decimal objects natively.*",
    category=SAWarning,
)

# The project directory, so the SQLite file lands beside the code rather than
# wherever the shell happened to be when the server was started. Running
# `python autopivot_backend.py` from the project root and running it from
# VS Code's Run panel would otherwise use two different databases, and the
# account you seeded would appear to have vanished.
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_SQLITE_PATH = BASE_DIR / "autopivot.db"


def get_database_url() -> str:
    """The configured database URL, defaulting to a local SQLite file.

    An explicit DATABASE_URL always wins, so pointing this at PostgreSQL is a
    one-line change in `.env`.
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    # as_posix() keeps the URL well-formed on Windows, where the path contains
    # backslashes that SQLAlchemy would otherwise read as escape characters.
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def is_sqlite(database_url: str | None = None) -> bool:
    return (database_url or get_database_url()).startswith("sqlite")


@lru_cache
def get_engine() -> Engine:
    database_url = get_database_url()

    if is_sqlite(database_url):
        engine = create_engine(
            database_url,
            # FastAPI serves requests from a thread pool, and a connection
            # opened on one thread is handed to another. SQLite's default
            # same-thread check rejects that; SQLAlchemy's connection pool is
            # what actually keeps concurrent use safe here.
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            # SQLite ignores foreign keys unless asked, per connection. The
            # schema leans on them heavily — a processing job is tied to its
            # listing and its backdrop by composite foreign keys that exist
            # specifically to keep one dealership's data away from another's.
            cursor.execute("PRAGMA foreign_keys=ON")
            # Write-ahead logging lets the reads a page does carry on while a
            # background processing job is writing, instead of failing with
            # "database is locked".
            cursor.execute("PRAGMA journal_mode=WAL")
            # Wait for a writer rather than giving up instantly. Image
            # processing holds its transaction longer than a web request does.
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
