"""Read .env, before anything that depends on it is imported.

This is separate from `api/config.py` because of *when* it has to run rather
than what it does. `huggingface_hub` and `transformers` read `HF_HOME` once, at
import time, and cache the answer. Loading `.env` after those imports — which
is what happens if the work is left to `api/config.py`, imported further down
the list — means the setting is read too late to have any effect, and several
gigabytes of models land in the default cache in your user profile instead of
where the file asked for.

So `autopivot_backend.py` calls `load_environment()` as its first statement.

Deliberately dependency-free beyond python-dotenv: importing anything heavier
here would reintroduce the ordering problem it exists to solve.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Settings that name a directory. A relative value in .env is read as relative
# to the project, not to the working directory, so the Run panel in VS Code and
# a terminal opened in a subfolder agree about where things are.
_PATH_SETTINGS = ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME", "STORAGE_ROOT")

_loaded = False


def load_environment() -> None:
    """Load .env and make its directory settings absolute. Safe to call twice."""
    global _loaded
    if _loaded:
        return

    # override=False: a variable already set in the shell beats the file, which
    # is what lets a one-off `set MAX_FILE_MB=50` work without editing .env.
    load_dotenv(BASE_DIR / ".env", override=False)

    for name in _PATH_SETTINGS:
        value = os.environ.get(name, "").strip()
        if value and not Path(value).is_absolute():
            resolved = (BASE_DIR / value).resolve()
            os.environ[name] = str(resolved)
            if name in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME"):
                # The libraries create their own subdirectories, but only if the
                # root already exists on some versions.
                resolved.mkdir(parents=True, exist_ok=True)

    _loaded = True
