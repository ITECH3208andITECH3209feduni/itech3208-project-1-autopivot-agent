"""Provision the initial AutoPivot platform administrator."""

from __future__ import annotations

import os
import secrets
import sys

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api.security import hash_password
from database.connection import get_engine
from database.models import User

load_dotenv(override=False)


def main() -> int:
    email = os.getenv("SEED_PLATFORM_ADMIN_EMAIL", "admin@autopivot.local").strip().lower()
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
