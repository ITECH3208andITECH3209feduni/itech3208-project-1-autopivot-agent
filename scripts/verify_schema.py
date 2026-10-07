"""Check that the database the application will read actually has its tables.

Migrations reporting success is not the same thing. A DATABASE_URL pointing
somewhere unexpected migrates one database while the application reads another,
and the first symptom is a login failing with `relation "users" does not exist`
long after the bring-up script said everything was fine.

Run after `alembic upgrade head`:

    python3 -m scripts.verify_schema

Exits non-zero with the missing tables named.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Runs as `python scripts/verify_schema.py` too, as scripts/seed_dealership.py
# does, rather than failing on "No module named 'database'".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

# Before anything reads DATABASE_URL. Without it a URL set only in .env is
# never seen, and this checks the default SQLite file instead of the database
# the application uses — the exact mismatch it exists to catch.
from api.env import load_environment  # noqa: E402

load_environment()

from database.base import Base  # noqa: E402
from database.connection import get_database_url, get_engine  # noqa: E402


def main() -> int:
    # Taken from the models rather than written out here, so a new table cannot
    # be added without this check knowing about it.
    expected = set(Base.metadata.tables)

    try:
        present = set(inspect(get_engine()).get_table_names())
    except Exception as exc:
        print(f"could not read the schema: {exc}", file=sys.stderr)
        return 1

    missing = expected - present
    if missing:
        # The URL is printed without its password so a mismatch is obvious.
        url = get_database_url()
        if "@" in url:
            scheme, _, rest = url.partition("://")
            url = f"{scheme}://…@{rest.partition('@')[2]}"
        print(f"tables missing after migration: {', '.join(sorted(missing))}", file=sys.stderr)
        print(f"database: {url}", file=sys.stderr)
        return 1

    print(f"{len(expected)} expected tables present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
