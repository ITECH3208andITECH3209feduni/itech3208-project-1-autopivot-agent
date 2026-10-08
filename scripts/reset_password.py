"""Reset a local AutoPivot account's password.

    .venv\Scripts\python.exe -m scripts.reset_password ana.reid@northshore.co.nz

Prompts for the new password (nothing is echoed or stored in shell history),
and asks for a password change again at next sign-in only if --temporary is
passed. For local development databases.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.env import load_environment  # noqa: E402

load_environment()

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from api.security import hash_password  # noqa: E402
from database.connection import get_engine  # noqa: E402
from database.models import User  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    temporary = "--temporary" in sys.argv
    if len(args) != 1:
        print(__doc__)
        return 2
    email = args[0].strip().lower()

    with Session(get_engine()) as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            emails = session.scalars(select(User.email).order_by(User.email)).all()
            print(f"No account with email {email}. Accounts in this database:")
            for e in emails:
                print(f"  {e}")
            return 1

        first = getpass.getpass("New password: ")
        if len(first) < 8:
            print("Use at least 8 characters.")
            return 1
        if getpass.getpass("Repeat it: ") != first:
            print("Those did not match. Nothing was changed.")
            return 1

        user.password_hash = hash_password(first)
        user.must_change_password = temporary
        user.token_version = (user.token_version or 0) + 1
        session.commit()

    print(f"Password updated for {email}. Sign in with it now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

