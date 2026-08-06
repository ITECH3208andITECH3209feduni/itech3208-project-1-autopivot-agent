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

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


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
        "PLATE_MODEL_ID",
        "nickmuchi/yolos-small-finetuned-license-plate-detection",
    ),
    device=os.getenv("DEVICE", "auto").lower(),
    segmentation_size=env_int("SEGMENTATION_SIZE", 1024),
    vehicle_confidence=env_float("VEHICLE_CONFIDENCE", 0.35),
    plate_confidence=env_float("PLATE_CONFIDENCE", 0.30),
    crop_padding_ratio=env_float("CROP_PADDING_RATIO", 0.08),
    plate_box_padding=env_int("PLATE_BOX_PADDING", 5),
    vehicle_classes=frozenset(env_list("VEHICLE_CLASSES", "car,truck,bus,motorcycle")),
)
