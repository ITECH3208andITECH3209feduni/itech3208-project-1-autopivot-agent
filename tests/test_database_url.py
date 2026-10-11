"""A DATABASE_URL as hosting providers hand it out still reaches PostgreSQL.

`fly postgres attach` (docs/DEPLOY_FLY.md), and most managed-Postgres
dashboards, give out URLs of the form `postgres://...`. SQLAlchemy 2 has no
dialect by that name and refuses it outright — on Fly, in the release command,
before the application ever started. The spelled-out `postgresql://...` means
"the default driver", which SQLAlchemy 2.0 takes to be psycopg2: not
installed, since requirements.txt installs psycopg 3 and allows any 2.x
SQLAlchemy. (2.1 made psycopg the default, which is why that case only fails
on a 2.0 install.)

get_database_url() is what the engine and Alembic's env.py both read, so that
is where the scheme is settled. Nothing but a driverless PostgreSQL scheme may
be rewritten.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from database.connection import get_database_url


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            "postgres://app:s3cret@db.internal:5432/autopivot?sslmode=disable",
            "postgresql+psycopg://app:s3cret@db.internal:5432/autopivot?sslmode=disable",
        ),
        (
            "postgresql://app:s3cret@db.internal/autopivot",
            "postgresql+psycopg://app:s3cret@db.internal/autopivot",
        ),
        # Pasted from a dashboard, with the whitespace that comes along.
        (
            "  postgres://app:pw@host/db\n",
            "postgresql+psycopg://app:pw@host/db",
        ),
    ],
)
def test_a_driverless_postgres_url_is_given_the_installed_driver(
    monkeypatch, configured, expected
):
    monkeypatch.setenv("DATABASE_URL", configured)

    assert get_database_url() == expected


@pytest.mark.parametrize(
    "configured",
    [
        "postgresql+psycopg://app:pw@host:5432/db",
        # Naming a driver is a decision someone made; it is not second-guessed.
        "postgresql+psycopg2://app:pw@host/db",
        "sqlite+pysqlite:////srv/autopivot/autopivot.db",
        "sqlite:///relative.db",
        "mysql://app:pw@host/db",
        # Only the scheme counts, not the same letters later in the URL.
        "postgresql+psycopg://postgres:postgres://x@host/db",
    ],
)
def test_every_other_url_is_left_exactly_as_configured(monkeypatch, configured):
    monkeypatch.setenv("DATABASE_URL", configured)

    assert get_database_url() == configured


@pytest.mark.parametrize(
    "configured",
    [
        "postgres://app:pw@db.internal:5432/autopivot",
        "postgresql://app:pw@db.internal:5432/autopivot",
    ],
)
def test_an_engine_can_be_built_from_a_provider_url(monkeypatch, configured):
    """What actually failed: building the engine, before any connection."""
    monkeypatch.setenv("DATABASE_URL", configured)

    # create_engine loads the dialect and imports its driver, and opens no
    # connection, so nothing here needs a server.
    engine = create_engine(get_database_url())
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()
