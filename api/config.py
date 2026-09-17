"""Settings shared by the light API and the full ML application.

Only values both halves need live here. Model paths, upload limits and the
HuggingFace token stay in autopivot_backend.py, since nothing in the light API
has any use for them.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env.example has always existed but nothing loaded it, so DATABASE_URL had to
# be exported by hand in every shell. Real environment variables still win.
load_dotenv(override=False)

BASE_DIR = Path(__file__).resolve().parent.parent

HOST: str = os.getenv("HOST", "0.0.0.0")
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
