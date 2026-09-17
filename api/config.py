"""Settings shared by the light API and the full ML application.

Only values both halves need live here. Model paths, upload limits and the
HuggingFace token stay in autopivot_backend.py, since nothing in the light API
has any use for them.
"""

from __future__ import annotations

import os

from api.env import BASE_DIR, load_environment

# .env is loaded by absolute path rather than by search. VS Code starts the
# debugger with the workspace folder as the working directory, but a terminal
# opened inside a subfolder does not, and load_dotenv's default search would
# then silently find nothing. Real environment variables still win.
#
# Calling it here as well as from autopivot_backend.py is what lets the light
# API — `uvicorn api.app:app` — read the same file. The call is idempotent.
load_environment()

# 127.0.0.1 rather than 0.0.0.0: this is a development machine, and there is no
# reason for a half-finished demo holding dealership data to be reachable from
# the rest of the network. Set HOST=0.0.0.0 to expose it deliberately — that is
# what a server or a tunnel needs.
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", 8000))

# The 5173 entries are the Vite dev server, which serves the React client on a
# different origin to this API during development.
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
