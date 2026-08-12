"""AutoPivot configuration.

What this file does: loads runtime/model settings from .env and defines the two
built-in showroom presets. The full-car preset keeps only the few layout values
needed to place a vehicle on the display base.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_list(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class BackgroundPreset:
    key: str
    label: str
    filename: str
    placement: str
    surface: str
    ground_y_ratio: float
    platform_box: tuple[float, float, float, float] | None = None
    platform_contact_y_ratio: float | None = None
    vehicle_width_ratio: float = 0.72
    vehicle_height_ratio: float = 0.60


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    host: str
    port: int
    log_level: str
    max_file_mb: int
    allowed_origins: tuple[str, ...]
    allowed_content_types: frozenset[str]
    api_v1_prefix: str

    hf_token: str
    rmbg_model_id: str
    birefnet_model_id: str
    preload_background_models: bool
    yolo_primary_hf_repo: str
    yolo_primary_model_path: str
    yolo_fallback_model_path: str
    enable_yolo_fallback: bool
    plate_model_id: str
    device: str

    segmentation_size: int
    vehicle_confidence: float
    plate_confidence: float
    crop_padding_ratio: float
    plate_box_padding: int
    vehicle_classes: frozenset[str]

    background_dir: Path
    default_background_style: str
    background_presets: tuple[BackgroundPreset, ...]
    output_width: int
    output_height: int

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    def background_preset(self, style: str | None) -> BackgroundPreset | None:
        return next((preset for preset in self.background_presets if preset.key == style), None)


settings = Settings(
    base_dir=BASE_DIR,
    host=os.getenv("HOST", "0.0.0.0"),
    port=env_int("PORT", 8000),
    log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    max_file_mb=env_int("MAX_FILE_MB", 20),
    allowed_origins=env_list(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost,https://localhost,capacitor://localhost",
    ),
    allowed_content_types=frozenset(
        env_list("ALLOWED_CONTENT_TYPES", "image/jpeg,image/png,image/webp")
    ),
    api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1").rstrip("/"),
    hf_token=os.getenv("HF_TOKEN", ""),
    rmbg_model_id=os.getenv("RMBG_MODEL_ID", "briaai/RMBG-2.0"),
    birefnet_model_id=os.getenv("BIREFNET_MODEL_ID", "ZhengPeng7/BiRefNet"),
    preload_background_models=env_bool("PRELOAD_BACKGROUND_MODELS", True),
    yolo_primary_hf_repo=os.getenv("YOLO_PRIMARY_HF_REPO", "Ultralytics/YOLO26"),
    yolo_primary_model_path=os.getenv("YOLO_PRIMARY_MODEL_PATH", "yolo26n.pt"),
    yolo_fallback_model_path=os.getenv("YOLO_FALLBACK_MODEL_PATH", "yolo11n.pt"),
    enable_yolo_fallback=env_bool("ENABLE_YOLO_FALLBACK", True),
    plate_model_id=os.getenv(
        "PLATE_MODEL_ID", "nickmuchi/yolos-small-finetuned-license-plate-detection"
    ),
    device=os.getenv("DEVICE", "auto").lower(),
    segmentation_size=env_int("SEGMENTATION_SIZE", 1024),
    vehicle_confidence=env_float("VEHICLE_CONFIDENCE", 0.35),
    plate_confidence=env_float("PLATE_CONFIDENCE", 0.30),
    crop_padding_ratio=env_float("CROP_PADDING_RATIO", 0.08),
    plate_box_padding=env_int("PLATE_BOX_PADDING", 5),
    vehicle_classes=frozenset(env_list("VEHICLE_CLASSES", "car,truck,bus,motorcycle")),
    background_dir=BASE_DIR / "assets" / "backgrounds",
    default_background_style=os.getenv("DEFAULT_BACKGROUND_STYLE", "studio_full"),
    background_presets=(
        BackgroundPreset(
            key="studio_full",
            label="AutoPivot Studio - Full Car",
            filename="studio-full.png",
            placement="ground",
            surface="display_base",
            ground_y_ratio=0.755,
            # x1, y1, x2, y2 as ratios of the 4:3 output canvas.
            platform_box=(0.105, 0.598, 0.875, 0.820),
            platform_contact_y_ratio=0.755,
            vehicle_width_ratio=0.86,
            vehicle_height_ratio=0.54,
        ),
        BackgroundPreset(
            key="studio_closeup",
            label="AutoPivot Studio - Close-up / Interior",
            filename="studio-closeup.png",
            placement="center",
            surface="wall",
            ground_y_ratio=0.82,
            vehicle_width_ratio=0.86,
            vehicle_height_ratio=0.78,
        ),
    ),
    output_width=env_int("OUTPUT_WIDTH", 1280),
    output_height=env_int("OUTPUT_HEIGHT", 960),
)
