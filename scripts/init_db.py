"""Create the database schema, whichever database is configured.

    python -m scripts.init_db

Replaces `alembic upgrade head` as the setup step on a local machine, because
the two databases need different treatment:

**SQLite** — the schema is built directly from `database/models.py` with
`create_all`, then Alembic is stamped at head so the migration history stays
consistent. The migrations themselves cannot run here: they were written
against PostgreSQL and use `UPDATE ... FROM`, bare `ALTER COLUMN` and
`DROP CONSTRAINT`, none of which SQLite implements. The end state is the same
schema either way — the migrations and the models describe the same tables.

`create_all` only creates tables that are missing. It never adds a column to a
table that already exists, so an `autopivot.db` built from older models comes
through it unchanged — and stamping that file at head would record it as
current when it is not, leaving the first login to fail with
`no such column: users.token_version`. So the file is compared with the models
before it is stamped, and if a column is missing the script names it, says how
to rebuild, and exits non-zero without stamping. It never alters or deletes
what is already there: bringing such a file up to date means rebuilding it, a
rebuilt database starts empty, and that is the developer's call to make.

**PostgreSQL** — `alembic upgrade head` is run, exactly as before. Nothing
about the deployed path changes.

Safe to re-run. `create_all` skips tables that already exist, and Alembic skips
revisions that have already been applied.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allows `python scripts/init_db.py` as well as `python -m scripts.init_db`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine, inspect  # noqa: E402

from api.env import load_environment  # noqa: E402
from database.base import Base  # noqa: E402
from database.connection import (  # noqa: E402
    BASE_DIR,
    get_database_url,
    get_engine,
    is_sqlite,
)
import database.models  # noqa: E402,F401  (registers every table on Base)

load_environment()


def alembic_config() -> Config:
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    return config


def compare_with_models(engine: Engine) -> tuple[list[str], list[str]]:
    """Columns the models declare that the database lacks, and the reverse.

    Each is written "table.column". Only names are compared, not types,
    defaults, constraints or indexes: a missing column is the difference that
    breaks the application outright, because loading a model selects every
    column it declares — one absent column fails every query on that table.

    A column the database has and the models do not — left by another branch,
    say — is never selected, so it is returned to be mentioned rather than
    treated as a problem. (It is mentioned at all because an insert into its
    table would still fail if it were NOT NULL with no default.)
    """
    in_database = {
        table: {column["name"] for column in reflected}
        for (_schema, table), reflected in inspect(engine).get_multi_columns().items()
    }
    missing: list[str] = []
    extra: list[str] = []
    for name, table in sorted(Base.metadata.tables.items()):
        present = in_database.get(name, set())
        declared = [column.name for column in table.columns]
        missing += [f"{name}.{column}" for column in declared if column not in present]
        extra += [f"{name}.{column}" for column in sorted(present) if column not in declared]
    return missing, extra


def report_missing_columns(db_path: str, missing: list[str]) -> None:
    name = Path(db_path).name
    lines = [
        "",
        "error: this database is older than database/models.py. It is missing:",
        "",
        *(f"  {column}" for column in missing),
        "",
        "Running this script again will not add them: create_all creates missing",
        "tables, never missing columns. The backend would fail with 'no such",
        "column' the first time it read one, so this stops here rather than",
        "stamping the file as current. Nothing that was already in the database",
        "has been changed or deleted.",
        "",
        "To rebuild it, stop the backend, then:",
        "",
        f"  1. Rename {db_path}",
        f"     to keep it as a backup (for example to {name}.old), along with",
        f"     {name}-wal and {name}-shm if they are there.",
        "  2. python -m scripts.init_db",
        "  3. python -m scripts.seed_dealership",
        "     (and python -m scripts.seed_platform_admin for the platform admin)",
        "",
        "The rebuilt database starts empty. Nothing in the old file is copied",
        "across: dealerships, accounts, listings and backdrops have to be created",
        "again, and you sign in with what seed_dealership prints.",
    ]
    # With output piped, stdout is buffered and stderr is not, so the progress
    # lines printed before this would otherwise turn up after it.
    sys.stdout.flush()
    print("\n".join(lines), file=sys.stderr)


def main() -> int:
    url = get_database_url()

    if is_sqlite(url):
        # The path matters more than the URL to someone looking for the file.
        db_path = url.split("///", 1)[-1]
        print(f"Database  : SQLite — {db_path}")
        print("Creating tables from database/models.py ...")

        engine = get_engine()
        Base.metadata.create_all(engine)

        # create_all has added every missing table by now, so anything still
        # missing is a column in a table that already existed — one holding the
        # developer's own rows. Changing those tables is not a decision to take
        # on their behalf, so the columns are named, the tables are left alone,
        # and the file is not stamped.
        missing, extra = compare_with_models(engine)
        if extra:
            print(
                "  Note: columns database/models.py does not declare, left as"
                f" they are: {', '.join(extra)}"
            )
        if missing:
            report_missing_columns(db_path, missing)
            return 1

        created = sorted(Base.metadata.tables)
        print(f"  {len(created)} tables ready: {', '.join(created)}")

        # Stamping records the migration history as fully applied without
        # running it. Without this, a later `alembic upgrade head` would try to
        # create tables that already exist.
        command.stamp(alembic_config(), "head")
        print("Alembic stamped at head.")
    else:
        print(f"Database  : PostgreSQL — {url.rsplit('@', 1)[-1]}")
        print("Running migrations ...")
        command.upgrade(alembic_config(), "head")
        print("Migrations applied.")

    print("\nNext: python -m scripts.seed_dealership")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
