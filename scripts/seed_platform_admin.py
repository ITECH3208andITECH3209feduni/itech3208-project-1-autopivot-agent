"""Provision the initial AutoPivot platform administrator.

    python -m scripts.seed_platform_admin
    python scripts/seed_platform_admin.py
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

# Lets this run as `python scripts/seed_platform_admin.py` as well as with -m,
# as scripts/seed_dealership.py does. Without it the file form fails on
# "No module named 'api'".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# Loads .env from the project directory, and before api.security is imported:
# that module reads JWT_SECRET once, at import time, and would otherwise warn
# about a key that .env does set.
from api.env import load_environment  # noqa: E402

load_environment()

from api.security import hash_password  # noqa: E402
from database.connection import get_engine  # noqa: E402
from database.models import User  # noqa: E402


def main() -> int:
    # The login API validates EmailStr; .local is reserved and cannot sign in.
    email = os.getenv("SEED_PLATFORM_ADMIN_EMAIL", "admin@autopivot.example.com").strip().lower()
    first_name = os.getenv("SEED_PLATFORM_ADMIN_FIRST_NAME", "AutoPivot").strip()
    last_name = os.getenv("SEED_PLATFORM_ADMIN_LAST_NAME", "Administrator").strip()
    password = os.getenv("SEED_PLATFORM_ADMIN_PASSWORD", "").strip()
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)

    if not email or not first_name or not last_name:
        print("error: platform administrator details must not be blank.", file=sys.stderr)
        return 1

    sessions = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with sessions() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            if existing.role != "platform_admin":
                print("error: that email belongs to a non-platform account.", file=sys.stderr)
                return 1
            print(f"Platform administrator already exists: {email}")
            return 0

        session.add(User(
            dealership_id=None,
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role="platform_admin",
            is_active=True,
            must_change_password=True,
        ))
        session.commit()

    print(f"Platform administrator created: {email}")
    if generated:
        print(f"Initial password: {password}")
        print("Shown once. It must be changed at first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
