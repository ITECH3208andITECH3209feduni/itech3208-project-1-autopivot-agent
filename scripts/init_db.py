"""Create the database schema, whichever database is configured."""

from __future__ import annotations

import sys
from pathlib import Path

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
    """Columns the models declare that the database lacks, and the reverse."""
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
    sys.stdout.flush()
    print("\n".join(lines), file=sys.stderr)


def main() -> int:
    url = get_database_url()

    if is_sqlite(url):
        db_path = url.split("///", 1)[-1]
        print(f"Database  : SQLite — {db_path}")
        print("Creating tables from database/models.py ...")

        engine = get_engine()
        Base.metadata.create_all(engine)

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

