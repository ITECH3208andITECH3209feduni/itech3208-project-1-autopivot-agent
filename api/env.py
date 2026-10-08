"""Read .env, before anything that depends on it is imported."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

_PATH_SETTINGS = ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME", "STORAGE_ROOT")

_loaded = False


def load_environment() -> None:
    """Load .env and make its directory settings absolute. Safe to call twice."""
    global _loaded
    if _loaded:
        return

    load_dotenv(BASE_DIR / ".env", override=False)

    for name in _PATH_SETTINGS:
        value = os.environ.get(name, "").strip()
        if value and not Path(value).is_absolute():
            resolved = (BASE_DIR / value).resolve()
            os.environ[name] = str(resolved)
            if name in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME"):
                resolved.mkdir(parents=True, exist_ok=True)

    _loaded = True

