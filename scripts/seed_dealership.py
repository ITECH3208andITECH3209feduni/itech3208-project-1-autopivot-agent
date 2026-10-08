"""Provision a dealership and its first administrator."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from api.env import load_environment

load_environment()

from api.security import hash_password  # noqa: E402
from database.connection import get_engine  # noqa: E402
from database.models import Dealership, User  # noqa: E402


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
            "The schema may not exist yet. Run 'python -m scripts.init_db' "
            "first, and check DATABASE_URL if you have set one.",
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

