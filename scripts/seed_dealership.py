"""Provision a dealership and its first administrator.

    alembic upgrade head
    python -m scripts.seed_dealership

Creates only what is needed to sign in: one dealership and one admin account.
No listings, no images, no backdrops — a new dealership starts empty and fills
up through the application.

Everything is configurable, so this doubles as the provisioning step for a real
dealership rather than being demo-only:

    SEED_DEALERSHIP_NAME='Northshore Motors'
    SEED_DEALERSHIP_LOCATION='Takapuna'
    SEED_ADMIN_EMAIL='ana.reid@northshore.co.nz'
    SEED_ADMIN_FIRST_NAME='Ana'
    SEED_ADMIN_LAST_NAME='Reid'
    SEED_ADMIN_PASSWORD='...'      # generated and printed once if unset

Safe to re-run: existing rows are matched on their natural keys and left alone.
"""

from __future__ import annotations

import os
import secrets
import sys

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from api.security import hash_password
from database.connection import get_engine
from database.models import Dealership, User

load_dotenv(override=False)


def config() -> dict[str, str]:
    return {
        "dealership": os.getenv("SEED_DEALERSHIP_NAME", "Northshore Motors").strip(),
        "location": os.getenv("SEED_DEALERSHIP_LOCATION", "Takapuna").strip(),
        "email": os.getenv("SEED_ADMIN_EMAIL", "ana.reid@northshore.co.nz").strip().lower(),
        "first_name": os.getenv("SEED_ADMIN_FIRST_NAME", "Ana").strip(),
        "last_name": os.getenv("SEED_ADMIN_LAST_NAME", "Reid").strip(),
    }


def seed_dealership(session: Session, cfg: dict[str, str]) -> Dealership:
    dealership = session.scalar(
        select(Dealership).where(Dealership.name == cfg["dealership"])
    )
    if dealership is None:
        dealership = Dealership(
            name=cfg["dealership"],
            location=cfg["location"] or None,
            status="active",
        )
        session.add(dealership)
        session.flush()
        print(f"  created dealership  {cfg['dealership']} (id={dealership.id})")
    else:
        print(f"  dealership exists   {cfg['dealership']} (id={dealership.id})")
    return dealership


def seed_admin(
    session: Session, dealership: Dealership, cfg: dict[str, str], password: str
) -> tuple[User, bool]:
    user = session.scalar(select(User).where(User.email == cfg["email"]))
    if user is not None:
        print(f"  admin exists        {cfg['email']}  (password unchanged)")
        return user, False

    user = User(
        dealership_id=dealership.id,
        email=cfg["email"],
        password_hash=hash_password(password),
        first_name=cfg["first_name"],
        last_name=cfg["last_name"],
        role="dealership_admin",
        is_active=True,
        # Provisioned accounts are forced through a password change on first
        # login, which is what the schema default already assumes.
        must_change_password=True,
    )
    session.add(user)
    session.flush()
    print(f"  created admin       {cfg['email']}")
    return user, True


def main() -> int:
    cfg = config()
    if not cfg["dealership"]:
        print("error: SEED_DEALERSHIP_NAME must not be blank.", file=sys.stderr)
        return 1

    password = os.getenv("SEED_ADMIN_PASSWORD", "").strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True

    try:
        engine = get_engine()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    print(f"Provisioning {cfg['dealership']}…")
    try:
        with session_factory() as session:
            dealership = seed_dealership(session, cfg)
            _, created = seed_admin(session, dealership, cfg, password)
            session.commit()
    except SQLAlchemyError as exc:
        print(f"\nerror: provisioning failed — {exc}", file=sys.stderr)
        print(
            "Check that DATABASE_URL points at a running database and that "
            "'alembic upgrade head' has been applied.",
            file=sys.stderr,
        )
        return 1

    print("\nDone. The dealership starts with no vehicles, images or backdrops.")
    if created and generated:
        print(f"  Sign in as : {cfg['email']}")
        print(f"  Password   : {password}")
        print("  Shown once. The account must change it at first login.")
    elif created:
        print(f"  Sign in as {cfg['email']} using SEED_ADMIN_PASSWORD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
