"""Make sure .env exists and has a lasting JWT_SECRET."""

from __future__ import annotations

import re
import secrets
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
EXAMPLE_PATH = BASE_DIR / ".env.example"
MIN_BYTES = 32
_PLACEHOLDERS = {"", "change_me", "changeme", "your-secret-here", "replace_me"}
_LINE = re.compile(r"^\s*JWT_SECRET\s*=(.*)$")


def _usable(value: str) -> bool:
    value = value.strip().strip('"').strip("'")
    return value.lower() not in _PLACEHOLDERS and len(value.encode("utf-8")) >= MIN_BYTES


def ensure_env(env_path: Path = ENV_PATH, example_path: Path = EXAMPLE_PATH) -> str:
    """Return what was done: 'created', 'added', 'replaced' or 'ok'."""
    created = False
    if not env_path.exists():
        if example_path.exists():
            shutil.copyfile(example_path, env_path)
        else:
            env_path.write_text("", encoding="utf-8")
        created = True

    raw = env_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8-sig").splitlines()
    secret = secrets.token_urlsafe(48)

    for index, line in enumerate(lines):
        match = _LINE.match(line)
        if match:
            if _usable(match.group(1)):
                return "created" if created else "ok"
            lines[index] = f"JWT_SECRET={secret}"
            action = "replaced"
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["# Login token signing key - generated once by scripts/ensure_env.py.",
                  f"JWT_SECRET={secret}"]
        action = "added"

    env_path.write_text(newline.join(lines) + newline, encoding="utf-8")
    return "created" if created else action


def main() -> int:
    result = ensure_env()
    messages = {
        "created": ".env created with a new JWT_SECRET.",
        "added": "JWT_SECRET added to .env - logins now survive restarts.",
        "replaced": "JWT_SECRET in .env was empty or too short - a new one was generated.",
        "ok": ".env already has a JWT_SECRET.",
    }
    print(messages[result])
    return 0


if __name__ == "__main__":
    sys.exit(main())

