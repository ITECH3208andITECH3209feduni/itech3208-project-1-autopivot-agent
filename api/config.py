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



def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


USE_DEFAULT_STUDIO_BACKGROUND: bool = _env_bool("USE_DEFAULT_STUDIO_BACKGROUND", True)
DEFAULT_STUDIO_BACKGROUND_PATH: Path = BASE_DIR / os.getenv(
    "DEFAULT_STUDIO_BACKGROUND_PATH",
    "assets/backgrounds/studio-full.png",
)

OUTPUT_WIDTH: int = _env_int("OUTPUT_WIDTH", 1280)
OUTPUT_HEIGHT: int = _env_int("OUTPUT_HEIGHT", 960)
VEHICLE_WIDTH_RATIO: float = _env_float("VEHICLE_WIDTH_RATIO", 0.72)
VEHICLE_HEIGHT_RATIO: float = _env_float("VEHICLE_HEIGHT_RATIO", 0.60)
GROUND_Y_RATIO: float = _env_float("GROUND_Y_RATIO", 0.84)

MASK_ERODE_PIXELS: int = _env_int("MASK_ERODE_PIXELS", 1)
MASK_CLOSE_KERNEL: int = _env_int("MASK_CLOSE_KERNEL", 3)
MASK_FEATHER_RADIUS: float = _env_float("MASK_FEATHER_RADIUS", 0.65)
TRIM_ALPHA_THRESHOLD: int = _env_int("TRIM_ALPHA_THRESHOLD", 4)
TRIM_PADDING: int = _env_int("TRIM_PADDING", 2)
PLACEMENT_ALPHA_THRESHOLD: int = _env_int("PLACEMENT_ALPHA_THRESHOLD", 6)

CONTACT_SHADOW_OPACITY: float = _env_float("CONTACT_SHADOW_OPACITY", 0.35)
AMBIENT_SHADOW_OPACITY: float = _env_float("AMBIENT_SHADOW_OPACITY", 0.15)
CONTACT_SHADOW_BLUR: float = _env_float("CONTACT_SHADOW_BLUR", 12.0)
AMBIENT_SHADOW_BLUR: float = _env_float("AMBIENT_SHADOW_BLUR", 24.0)
CONTACT_SHADOW_HEIGHT_RATIO: float = _env_float("CONTACT_SHADOW_HEIGHT_RATIO", 0.075)
AMBIENT_SHADOW_HEIGHT_RATIO: float = _env_float("AMBIENT_SHADOW_HEIGHT_RATIO", 0.14)
CONTACT_SHADOW_WIDTH_SCALE: float = _env_float("CONTACT_SHADOW_WIDTH_SCALE", 0.90)
AMBIENT_SHADOW_WIDTH_SCALE: float = _env_float("AMBIENT_SHADOW_WIDTH_SCALE", 1.04)
SHADOW_Y_OFFSET: int = _env_int("SHADOW_Y_OFFSET", -2)

HARMONIZATION_STRENGTH: float = _env_float("HARMONIZATION_STRENGTH", 0.15)
HARMONIZATION_MAX_AB_SHIFT: float = _env_float("HARMONIZATION_MAX_AB_SHIFT", 5.0)
EXPOSURE_MATCH_STRENGTH: float = _env_float("EXPOSURE_MATCH_STRENGTH", 0.12)
EXPOSURE_MAX_L_SHIFT: float = _env_float("EXPOSURE_MAX_L_SHIFT", 18.0)
LIGHTING_TRANSFER_STRENGTH: float = _env_float("LIGHTING_TRANSFER_STRENGTH", 0.16)
LIGHTING_MAX_L_SHIFT: float = _env_float("LIGHTING_MAX_L_SHIFT", 7.0)

PLATFORM_TOP_LEFT_RATIO: float = _env_float("PLATFORM_TOP_LEFT_RATIO", 0.105)
PLATFORM_TOP_TOP_RATIO: float = _env_float("PLATFORM_TOP_TOP_RATIO", 0.598)
PLATFORM_TOP_RIGHT_RATIO: float = _env_float("PLATFORM_TOP_RIGHT_RATIO", 0.875)
PLATFORM_TOP_BOTTOM_RATIO: float = _env_float("PLATFORM_TOP_BOTTOM_RATIO", 0.820)
PLATFORM_OUTER_LEFT_RATIO: float = _env_float("PLATFORM_OUTER_LEFT_RATIO", 0.098)
PLATFORM_OUTER_TOP_RATIO: float = _env_float("PLATFORM_OUTER_TOP_RATIO", 0.592)
PLATFORM_OUTER_RIGHT_RATIO: float = _env_float("PLATFORM_OUTER_RIGHT_RATIO", 0.882)
PLATFORM_OUTER_BOTTOM_RATIO: float = _env_float("PLATFORM_OUTER_BOTTOM_RATIO", 0.855)
PLATFORM_CONTACT_Y_RATIO: float = _env_float("PLATFORM_CONTACT_Y_RATIO", 0.755)
PLATFORM_CONTACT_SINK_PIXELS: int = _env_int("PLATFORM_CONTACT_SINK_PIXELS", 2)
PLATFORM_VEHICLE_WIDTH_RATIO: float = _env_float("PLATFORM_VEHICLE_WIDTH_RATIO", 0.86)
PLATFORM_VEHICLE_MAX_HEIGHT_RATIO: float = _env_float("PLATFORM_VEHICLE_MAX_HEIGHT_RATIO", 0.54)
PLATFORM_CONTACT_PERCENTILE: float = _env_float("PLATFORM_CONTACT_PERCENTILE", 0.97)
PLATFORM_CONTACT_ALPHA_THRESHOLD: int = _env_int("PLATFORM_CONTACT_ALPHA_THRESHOLD", 96)
PLATFORM_SHADOW_CLIP_ENABLED: bool = _env_bool("PLATFORM_SHADOW_CLIP_ENABLED", True)
PLATFORM_FRONT_RIM_ENABLED: bool = _env_bool("PLATFORM_FRONT_RIM_ENABLED", True)
