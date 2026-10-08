"""Create the database schema, whichever database is configured."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

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


def main() -> int:
    url = get_database_url()

    if is_sqlite(url):
        db_path = url.split("///", 1)[-1]
        print(f"Database  : SQLite — {db_path}")
        print("Creating tables from database/models.py ...")

        engine = get_engine()
        Base.metadata.create_all(engine)

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

