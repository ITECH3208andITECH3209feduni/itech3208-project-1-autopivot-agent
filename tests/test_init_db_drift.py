"""scripts/init_db.py must not stamp an SQLite file the models have outgrown.

`create_all` creates the tables that are missing and nothing else — it never
adds a column to a table that already exists. So a local autopivot.db built
from older models came through a re-run of init_db unchanged, was then stamped
at head as if it were current, and the first login afterwards failed with
`sqlite3.OperationalError: no such column: users.token_version`.

Every database here is an SQLite file under pytest's tmp_path, written by hand
where its age is the point. DATABASE_URL is set for each test, so neither the
repository's autopivot.db nor a DATABASE_URL in a developer's .env is touched:
the environment beats .env, because api.env loads it with override=False.

    pytest tests/test_init_db_drift.py -v
"""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

import scripts.init_db as init_db
from database.base import Base
from database.connection import get_database_url, get_engine

ROOT = Path(__file__).resolve().parent.parent

# Read from the migration files rather than written out, so adding a migration
# does not break these tests: the script is meant to stamp whatever head is.
HEAD = ScriptDirectory(str(ROOT / "migrations")).get_current_head()

# dealerships and users as create_all built them before contact_name,
# contact_email, contact_phone and token_version existed — database/models.py
# as it stood when init_db was introduced. Written out rather than derived from
# the models, so the fixture cannot pick up the columns it exists to leave out.
OLD_SCHEMA = """
CREATE TABLE dealerships (
    id INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    location VARCHAR(120),
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_dealerships PRIMARY KEY (id)
);
CREATE TABLE users (
    id INTEGER NOT NULL,
    dealership_id INTEGER,
    email VARCHAR(320) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    role VARCHAR(30) NOT NULL,
    is_active BOOLEAN DEFAULT 'true' NOT NULL,
    must_change_password BOOLEAN DEFAULT 'true' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT user_dealership_pair UNIQUE (id, dealership_id),
    CONSTRAINT fk_users_dealership_id_dealerships
        FOREIGN KEY(dealership_id) REFERENCES dealerships (id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX ix_users_email ON users (email);

INSERT INTO dealerships (id, name) VALUES (1, 'Northshore Motors');
INSERT INTO users (id, dealership_id, email, password_hash, first_name, last_name, role)
VALUES (1, 1, 'ana.reid@northshore.co.nz', 'not-a-real-hash', 'Ana', 'Reid',
        'dealership_admin');
"""

# What the previous init_db left behind on a file like the one above: the
# history marked as fully applied. Written the way Alembic writes it.
STAMP_AT_HEAD = f"""
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO alembic_version (version_num) VALUES ('{HEAD}');
"""


# ── Reading and writing the file directly, not through the code under test ──
def run_sql(path: Path, script: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(script)
        connection.commit()
    finally:
        connection.close()


def query(path: Path, sql: str) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def columns(path: Path, table: str) -> list[str]:
    return [row[1] for row in query(path, f"PRAGMA table_info({table})")]


def tables(path: Path) -> set[str]:
    return {row[0] for row in query(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def stamped_revision(path: Path) -> str | None:
    if "alembic_version" not in tables(path):
        return None
    rows = query(path, "SELECT version_num FROM alembic_version")
    return rows[0][0] if rows else None


def build_current_schema(path: Path, *, leave_out: tuple[str, ...] = ()) -> None:
    """The schema the models describe today, built the way init_db builds it."""
    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(
            engine,
            tables=[t for name, t in Base.metadata.tables.items() if name not in leave_out],
        )
    finally:
        engine.dispose()


# ── Fixtures ──
@pytest.fixture(autouse=True)
def keep_logging_as_it_was():
    # Stamping runs migrations/env.py, which calls logging.config.fileConfig()
    # on alembic.ini. That disables every logger already created and gives the
    # root logger a StreamHandler bound to this test's captured stderr, which is
    # closed when the test ends. Left in place, later tests in the session lose
    # their log output and report "I/O operation on closed file" instead.
    existing = {
        logger: logger.disabled
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    }
    root = logging.getLogger()
    handlers_before = set(root.handlers)
    yield
    for logger, disabled in existing.items():
        logger.disabled = disabled
    for handler in root.handlers[:]:
        if handler not in handlers_before and type(handler) is logging.StreamHandler:
            root.removeHandler(handler)


@pytest.fixture
def use_database(monkeypatch):
    """Point init_db at a file for this test only."""

    def point(path: Path) -> Path:
        url = f"sqlite+pysqlite:///{path.as_posix()}"
        monkeypatch.setenv("DATABASE_URL", url)
        # get_engine() is cached for the life of the process and would hand
        # back whichever database an earlier caller opened.
        get_engine.cache_clear()
        assert get_database_url() == url
        return path

    yield point
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


@pytest.fixture
def old_database(tmp_path) -> Path:
    path = tmp_path / "autopivot.db"
    run_sql(path, OLD_SCHEMA)
    return path


def run_init_db(capsys) -> tuple[int, str]:
    status = init_db.main()
    captured = capsys.readouterr()
    return status, captured.out + captured.err


# ── A database missing columns ──
@pytest.mark.parametrize(
    "already_stamped",
    [False, True],
    ids=["never-stamped", "stamped-at-head-by-the-old-init_db"],
)
def test_a_database_missing_columns_fails_and_is_not_stamped(
    old_database, use_database, capsys, already_stamped
):
    # The second case is every developer who has already hit the bug: their
    # file carries a head stamp it never earned, so the stamp cannot be what
    # decides whether the file is current.
    if already_stamped:
        run_sql(old_database, STAMP_AT_HEAD)
    stamp_before = stamped_revision(old_database)
    use_database(old_database)

    status, _ = run_init_db(capsys)

    assert status != 0
    assert stamped_revision(old_database) == stamp_before


def test_the_failure_names_each_missing_column(old_database, use_database, capsys):
    use_database(old_database)

    _, output = run_init_db(capsys)

    for missing in (
        "users.token_version",
        "dealerships.contact_name",
        "dealerships.contact_email",
        "dealerships.contact_phone",
    ):
        assert missing in output, f"{missing} is not named in:\n{output}"
    # A column the old table does have is not part of the problem.
    assert "users.email" not in output


def test_a_database_missing_columns_keeps_its_rows_and_columns(
    old_database, use_database, capsys
):
    # Bringing the file up to date means rebuilding it, which empties it. That
    # is the developer's decision, so the script must not take it for them —
    # not by rebuilding, and not by altering the tables it found.
    columns_before = columns(old_database, "users")
    use_database(old_database)

    run_init_db(capsys)

    assert columns(old_database, "users") == columns_before
    assert query(old_database, "SELECT email FROM users") == [("ana.reid@northshore.co.nz",)]
    assert query(old_database, "SELECT name FROM dealerships") == [("Northshore Motors",)]


@pytest.mark.parametrize(
    "command",
    [["scripts/init_db.py"], ["-m", "scripts.init_db"]],
    ids=["python scripts/init_db.py", "python -m scripts.init_db"],
)
def test_the_command_exits_non_zero_on_a_database_missing_columns(old_database, command):
    # setup.sh runs under `set -e` and setup.bat checks errorlevel: the exit
    # status is what stops setup from carrying on to seed a broken database.
    env = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{old_database.as_posix()}"}

    result = subprocess.run(
        [sys.executable, *command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "users.token_version" in result.stdout + result.stderr
    assert stamped_revision(old_database) is None


# ── Databases that match: behaviour as before ──
def test_a_new_database_is_created_and_stamped_at_head(tmp_path, use_database, capsys):
    path = use_database(tmp_path / "autopivot.db")

    status, output = run_init_db(capsys)

    assert status == 0, output
    assert stamped_revision(path) == HEAD
    assert "token_version" in columns(path, "users")


def test_running_again_on_a_current_database_succeeds(tmp_path, use_database, capsys):
    path = use_database(tmp_path / "autopivot.db")
    assert run_init_db(capsys)[0] == 0

    status, output = run_init_db(capsys)

    assert status == 0, output
    assert stamped_revision(path) == HEAD


def test_a_missing_table_is_created_rather_than_reported(tmp_path, use_database, capsys):
    # A table the models added since the file was built is exactly what
    # create_all is for, so it is not a reason to stop.
    path = tmp_path / "autopivot.db"
    build_current_schema(path, leave_out=("audit_logs",))
    use_database(path)

    status, output = run_init_db(capsys)

    assert status == 0, output
    assert "audit_logs" in tables(path)
    assert stamped_revision(path) == HEAD


def test_columns_the_models_do_not_declare_are_not_an_error(tmp_path, use_database, capsys):
    # A column left behind by another branch breaks nothing that reads the
    # models, and refusing over it would block a developer for no reason.
    path = tmp_path / "autopivot.db"
    build_current_schema(path)
    run_sql(path, "ALTER TABLE users ADD COLUMN nickname VARCHAR(50);")
    use_database(path)

    status, output = run_init_db(capsys)

    assert status == 0, output
    assert stamped_revision(path) == HEAD
    assert "nickname" in columns(path, "users")
