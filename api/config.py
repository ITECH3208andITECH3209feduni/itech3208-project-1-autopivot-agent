"""Settings shared by the light API and the full ML application."""

from __future__ import annotations

import os

from api.env import BASE_DIR, load_environment

load_environment()

HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", 8000))

ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]

