from __future__ import annotations

import base64
import dataclasses
import io
import logging
import logging.config
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, Body
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from huggingface_hub import get_token, hf_hub_download, login
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from ultralytics import YOLO

import classification
import compositing
from api import processing, url_import
from api.app import create_app
from api.config import BASE_DIR, HOST, PORT


# ── Configuration ──────────────────────────────────────────────────────────────

HF_TOKEN: str       = os.getenv("HF_TOKEN", "")
HF_AUTH_TOKEN: str  = HF_TOKEN or (get_token() or "")
MAX_FILE_MB: int    = int(os.getenv("MAX_FILE_MB", 20))
MAX_FILE_BYTES: int = MAX_FILE_MB * 1024 * 1024

YOLO_HF_REPO: str    = os.getenv("YOLO_HF_REPO", "Ultralytics/YOLO26")
YOLO_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "yolo26n.pt")

YOLO_FALLBACK_MODEL_PATH: str = os.getenv("YOLO_FALLBACK_MODEL_PATH", "yolo11n.pt")
ENABLE_YOLO_FALLBACK: bool = os.getenv(
    "ENABLE_YOLO_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}

# ── Licence plate handling ──
PLATE_CONFIDENCE: float = float(os.getenv("PLATE_CONFIDENCE", "0.30"))
PLATE_BOX_PADDING: int = int(os.getenv("PLATE_BOX_PADDING", "5"))

PLATE_MIN_ASPECT: float = float(os.getenv("PLATE_MIN_ASPECT", "1.2"))
PLATE_MAX_ASPECT: float = float(os.getenv("PLATE_MAX_ASPECT", "6.5"))

PLATE_MAX_AREA_RATIO: float = float(os.getenv("PLATE_MAX_AREA_RATIO", "0.12"))

PLATE_MIN_COVERAGE: float = float(os.getenv("PLATE_MIN_COVERAGE", "0.55"))

PLATE_INVISIBLE_ANGLES: frozenset[str] = frozenset({"side"})

PLATE_ZONE_MIN_SATURATION: int = int(os.getenv("PLATE_ZONE_MIN_SATURATION", "80"))
PLATE_ZONE_X_RATIO: tuple[float, float] = (0.05, 0.95)
PLATE_ZONE_Y_RATIO: tuple[float, float] = (0.45, 0.93)
PLATE_ZONE_MIN_EXTENT: float = float(os.getenv("PLATE_ZONE_MIN_EXTENT", "0.70"))
PLATE_ZONE_MIN_AREA_PX: int = int(os.getenv("PLATE_ZONE_MIN_AREA_PX", "120"))

PLATE_ZONE_MIN_WIDTH_RATIO: float = float(os.getenv("PLATE_ZONE_MIN_WIDTH_RATIO", "0.12"))

PLATE_TREATMENTS: frozenset[str] = frozenset({"blur", "pixelate", "white"})
PLATE_TREATMENT: str = os.getenv("PLATE_TREATMENT", "blur").strip().lower()
if PLATE_TREATMENT not in PLATE_TREATMENTS:
    logging.getLogger("autopivot").warning(
        "PLATE_TREATMENT=%r is not one of %s — using 'blur'.",
        PLATE_TREATMENT, ", ".join(sorted(PLATE_TREATMENTS)),
    )
    PLATE_TREATMENT = "blur"

PLATE_MOSAIC_WIDTH: int = int(os.getenv("PLATE_MOSAIC_WIDTH", "8"))

PLATE_BRAND_LOGO_ENABLED: bool = os.getenv(
    "PLATE_BRAND_LOGO_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
PLATE_BRAND_LOGO_PATH: str = os.getenv(
    "PLATE_BRAND_LOGO_PATH", str(BASE_DIR / "assets" / "autopivot-plate-logo.png")
)

# ── Image classification ──
CLASSIFY_IMAGES: bool = os.getenv(
    "CLASSIFY_IMAGES", "true"
).strip().lower() in {"1", "true", "yes", "on"}

_NOT_A_VEHICLE_PHOTO: dict[str, str] = {
    "advertisement": (
        "This looks like an advertisement or a dealer badge rather than a "
        "photograph of the vehicle."
    ),
    "interior": "This is an interior shot, so there is no exterior to place on a backdrop.",
    "detail": "This is a close-up of part of the vehicle rather than the whole car.",
    "unknown": (
        "This could not be identified as a photograph of the vehicle's exterior."
    ),
}

_VEHICLE_CROPPED_BY_FRAME = (
    "Part of the car runs past the edge of this photograph, so the whole "
    "body isn't in frame."
)

_SEGMENTATION_INCOMPLETE = (
    "Background removal did not keep the whole vehicle — part of the body "
    "came back transparent, most often a dark car against a low-contrast "
    "background. Flagged for review rather than published looking like "
    "only part of the car."
)

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
VEHICLE_CLASSES: frozenset[str] = frozenset(
    {"car", "truck", "bus", "motorcycle"}
)

YOLO26_HF_FILES: frozenset[str] = frozenset({
    "yolo26n.pt",
    "yolo26s.pt",
    "yolo26m.pt",
    "yolo26l.pt",
    "yolo26x.pt",
})
YOLO26_FILENAME_ALIASES: dict[str, str] = {
    "yolov26n.pt": "yolo26n.pt",
    "yolov26s.pt": "yolo26s.pt",
    "yolov26m.pt": "yolo26m.pt",
    "yolov26l.pt": "yolo26l.pt",
    "yolov26x.pt": "yolo26x.pt",
}

# ── Structured Logging ─────────────────────────────────────────────────────────

_LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
        # TEMPORARY — remove later
        "debug_file": {
            "class": "logging.FileHandler",
            "formatter": "standard",
            "filename": str(BASE_DIR / "debug_pipeline.log"),
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "debug_file"], "level": "INFO"},
}

logging.config.dictConfig(_LOGGING_CONFIG)
logger = logging.getLogger("autopivot")

# ── Shared Segmentation Transform ──────────────────────────────────────────────

_SEG_SIZE = (1024, 1024)
_seg_transform = transforms.Compose([
    transforms.Resize(_SEG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

# ── Model Registry ─────────────────────────────────────────────────────────────


class ModelRegistry:
    """Centralised model registry with lazy loading and per-model health tracking."""

    def __init__(self) -> None:
        self._rmbg: Optional[AutoModelForImageSegmentation] = None
        self._birefnet: Optional[AutoModelForImageSegmentation] = None
        self._rmbg_ok = False
        self._birefnet_ok = False

        self._vehicle: Optional[YOLO] = None
        self._plates = None
        self._vehicle_ok = False
        self._plates_ok = False

        self.active_yolo: str = "none"
        self.active_yolo_role: str = "none"

        self._device: str = "cuda" if torch.cuda.is_available() else "cpu"

        self._vehicle_lock = threading.RLock()
        self._plates_lock = threading.RLock()
        self._bg_lock = threading.RLock()

    # ── Read-only properties ──

    @property
    def device(self) -> str:
        return self._device

    @property
    def vehicle_detector(self) -> YOLO:
        if not self._vehicle_ok:
            self._load_vehicle()
        return self._vehicle  # type: ignore[return-value]

    @property
    def plate_detector(self):
        if not self._plates_ok:
            self._load_plates()
        return self._plates

    # ── Background model loaders ──

    def _load_rmbg(self) -> None:
        """Load BRIA RMBG-2.0 as the primary background removal model; requires
        a HuggingFace token that has accepted the BRIA licence."""
        logger.info("Loading primary background model — briaai/RMBG-2.0")
        try:
            self._rmbg = (
                AutoModelForImageSegmentation.from_pretrained(
                    "briaai/RMBG-2.0",
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                    token=HF_AUTH_TOKEN or True,
                )
                .eval()
                .to(self._device)
            )
            self._rmbg_ok = True
            logger.info("RMBG-2.0 loaded on %s", self._device)
        except Exception as exc:
            logger.warning(
                "RMBG-2.0 failed to load: %s. Falling back to BiRefNet.",
                exc,
                exc_info=True,
            )

    def _load_birefnet(self) -> None:
        """Load BiRefNet as the fallback background removal model, used
        whenever RMBG-2.0 is unavailable."""
        with self._bg_lock:
            if self._birefnet_ok:
                return

            logger.info("Loading fallback background model — ZhengPeng7/BiRefNet")
            try:
                self._birefnet = (
                    AutoModelForImageSegmentation.from_pretrained(
                        "ZhengPeng7/BiRefNet",
                        trust_remote_code=True,
                        torch_dtype=torch.float32,
                    )
                    .eval()
                    .to(self._device)
                )
                self._birefnet_ok = True
                logger.info("BiRefNet loaded on %s", self._device)
            except Exception as exc:
                logger.critical("BiRefNet failed to load: %s", exc, exc_info=True)
                raise RuntimeError(f"BiRefNet model unavailable: {exc}") from exc

    # ── Detection model loaders ──

    def load_vehicle_fallback(self) -> None:
        """Load the secondary vehicle detector."""
        if not ENABLE_YOLO_FALLBACK:
            raise RuntimeError("YOLO fallback is disabled by ENABLE_YOLO_FALLBACK")

        logger.info("Loading fallback vehicle detector — %s", YOLO_FALLBACK_MODEL_PATH)
        self._vehicle = YOLO(YOLO_FALLBACK_MODEL_PATH)
        self._vehicle_ok = True
        self.active_yolo = str(YOLO_FALLBACK_MODEL_PATH)
        self.active_yolo_role = "fallback"
        logger.info("Fallback detector loaded: %s", YOLO_FALLBACK_MODEL_PATH)

    def _load_vehicle(self) -> None:
        """Load the YOLO vehicle detector, falling back to YOLO11 if it fails."""
        with self._vehicle_lock:
            if self._vehicle_ok:
                return

            logger.info("Loading YOLO vehicle detector — %s", YOLO_MODEL_PATH)
            try:
                model_path = _resolve_yolo_model_path(YOLO_MODEL_PATH)
                self._vehicle = YOLO(model_path)
                self._vehicle_ok = True
                self.active_yolo = str(model_path)
                self.active_yolo_role = "primary"
                logger.info("YOLO loaded: %s", model_path)
                return
            except Exception as exc:
                logger.warning(
                    "YOLO model '%s' failed to load: %s",
                    YOLO_MODEL_PATH, exc, exc_info=True,
                )

            try:
                self.load_vehicle_fallback()
            except Exception as exc:
                logger.critical("Fallback detector also failed: %s", exc, exc_info=True)
                raise RuntimeError(
                    f"No vehicle detector available "
                    f"(primary={YOLO_MODEL_PATH}, fallback={YOLO_FALLBACK_MODEL_PATH}): {exc}"
                ) from exc

    def _load_plates(self) -> None:
        with self._plates_lock:
            if self._plates_ok:
                return

            logger.info("Loading YOLOS plate detector")
            try:
                self._plates = pipeline(
                    "object-detection",
                    model="nickmuchi/yolos-small-finetuned-license-plate-detection",
                )
                self._plates_ok = True
                logger.info("YOLOS plate detector loaded")
            except Exception as exc:
                logger.critical("Plate detector failed to load: %s", exc, exc_info=True)
                raise RuntimeError(f"Plate detector unavailable: {exc}") from exc

    # ── Active model resolution ──

    def active_bg_model(self):
        """Return the active background removal model and its identifier."""
        if self._rmbg_ok:
            return self._rmbg, "briaai/RMBG-2.0"
        if self._birefnet_ok:
            return self._birefnet, "ZhengPeng7/BiRefNet"
        raise RuntimeError(
            "No background removal model is loaded. "
            "Check startup logs for RMBG-2.0 / BiRefNet errors."
        )

    def health(self) -> dict:
        if self._rmbg_ok:
            active_bg = "briaai/RMBG-2.0"
        elif self._birefnet_ok:
            active_bg = "ZhengPeng7/BiRefNet (fallback)"
        else:
            active_bg = "none"

        return {
            "device": self._device,
            "active_bg_model": active_bg,
            "rmbg_loaded": self._rmbg_ok,
            "birefnet_loaded": self._birefnet_ok,
            "active_yolo_model": self.active_yolo,
            "active_yolo_role": self.active_yolo_role,
            "vehicle_detector_loaded": self._vehicle_ok,
            "plate_detector_loaded": self._plates_ok,
        }


registry = ModelRegistry()

# ── Pipeline Adapter ───────────────────────────────────────────────────────────


class PipelineProcessor:
    """Runs the full pipeline over raw bytes and reports what it found."""

    def process(
        self,
        image: bytes,
        background: Optional[bytes],
        ground_y_ratio: Optional[float] = None,
    ) -> processing.ProcessOutcome:
        source = _open_image(image).convert("RGB")

        classified = _classify(source)
        if classified is not None and not classification.is_processable(classified):
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind,
                kind_confidence=classified.kind_confidence,
                message=_NOT_A_VEHICLE_PHOTO.get(
                    classified.kind, "This photograph is not a vehicle exterior."
                ),
            )

        vehicle = _detect_vehicle(source)
        if vehicle is None:
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message="No vehicle detected in this photograph.",
            )

        if _vehicle_is_cropped_by_frame(vehicle["box"], source.size):
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message=_VEHICLE_CROPPED_BY_FRAME,
            )

        crop, coords = _crop_with_padding(source, vehicle["box"])
        bg_removed, model_used = _remove_background(crop)

        vehicle_box_in_crop = _box_in_crop(vehicle["box"], coords)
        if _segmentation_dropped_the_vehicle(bg_removed, vehicle_box_in_crop):
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message=_SEGMENTATION_INCOMPLETE,
            )

        plates = _detect_plates(crop) + _detect_plate_zone_stickers(crop, vehicle_box_in_crop)
        plates = _filter_plates(
            plates,
            _box_area(vehicle["box"]),
            bg_removed,
            angle=classified.angle if classified else None,
        )
        brand_overlay = _brand_plate_overlay()
        bg_removed = _apply_plate_treatment(bg_removed, plates, brand_overlay)

        # TEMPORARY — remove later
        try:
            debug_path = BASE_DIR / "debug_last_cutout.png"
            bg_removed.save(debug_path, format="PNG")
            logger.info("[QDIAG] saved raw cutout (post plate-treatment) to %s", debug_path)
        except Exception:
            logger.exception("[QDIAG] failed to save debug cutout")

        background_image = _open_image(background) if background else None
        angle = classified.angle if classified else None
        angle_confidence = classified.angle_confidence if classified else None
        # TEMPORARY — remove later
        logger.info(
            "[QDIAG] job angle=%s angle_confidence=%s", angle, angle_confidence
        )
        final, _ = _place_on_backdrop(
            bg_removed, background_image, source.size, coords,
            angle=angle, ground_y_ratio=ground_y_ratio,
            angle_confidence=angle_confidence,
        )

        buffer = io.BytesIO()
        final.save(buffer, format="PNG")

        return processing.ProcessOutcome(
            image_png=buffer.getvalue(),
            vehicle_detected=True,
            plates_detected=len(plates),
            plate_treatment=(
                "overlay" if plates and brand_overlay is not None
                else (PLATE_TREATMENT if plates else "none")
            ),
            model_used=model_used,
            detected_angle=angle,
            angle_confidence=angle_confidence,
            image_kind=classified.kind if classified else None,
            kind_confidence=classified.kind_confidence if classified else None,
        )


# ── Application Lifespan ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    if HF_TOKEN:
        try:
            login(token=HF_TOKEN)
            logger.info("HuggingFace authentication successful")
        except Exception as exc:
            logger.warning("HuggingFace login failed: %s", exc)
    elif HF_AUTH_TOKEN:
        logger.info("Using HuggingFace token from local hf auth login cache")
    else:
        logger.warning(
            "HF_TOKEN is not set. RMBG-2.0 requires authentication — "
            "BiRefNet will be used as the fallback. Set HF_TOKEN and accept "
            "the BRIA license at https://huggingface.co/briaai/RMBG-2.0 "
            "to enable the primary model."
        )

    # Step 1 — try primary model
    registry._load_rmbg()

    # Step 2 — if primary failed, load fallback (fatal if also fails)
    if not registry._rmbg_ok:
        registry._load_birefnet()

    processing.set_processor(PipelineProcessor())

    logger.info(
        "AutoPivot ready — device=%s  active_bg_model=%s  yolo=%s",
        registry.device,
        registry.health()["active_bg_model"],
        registry.active_yolo,
    )
    yield
    logger.info("AutoPivot shutting down")


# ── FastAPI Application ────────────────────────────────────────────────────────

app = create_app(
    lifespan=lifespan,
    description=(
        "Vehicle background removal, detection, and licence-plate treatment API. "
        "Developed by Vadim Rudoi."
    ),
)


# ── Validation Helpers ─────────────────────────────────────────────────────────


def _validate_upload(file: UploadFile, content: bytes) -> None:
    """Raise HTTP 413 / 415 for oversized or unsupported uploads."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported media type '{file.content_type}'. "
                "Accepted formats: JPEG, PNG, WEBP."
            ),
        )
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds the {MAX_FILE_MB} MB limit.",
        )


def _open_image(content: bytes) -> Image.Image:
    """Safely decode image bytes; corrupt or non-image payloads surface as HTTP 400."""
    try:
        probe = Image.open(io.BytesIO(content))
        probe.verify()
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Cannot identify image file.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {exc}")
    return Image.open(io.BytesIO(content))


async def _read_optional_image(upload: Optional[UploadFile]) -> Optional[Image.Image]:
    """Read and decode an optional UploadFile; return None if not provided."""
    if upload is None or not upload.filename:
        return None
    content = await upload.read()
    _validate_upload(upload, content)
    return _open_image(content)


def _encode_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _resolve_yolo_model_path(model_ref: str) -> str:
    """Resolve a YOLO model reference to a local file path that Ultralytics can load."""
    resolved_ref = YOLO26_FILENAME_ALIASES.get(model_ref, model_ref)
    candidate = Path(resolved_ref).expanduser()
    if candidate.exists():
        return str(candidate)

    if resolved_ref in YOLO26_HF_FILES:
        logger.info(
            "Downloading YOLO vehicle detector from Hugging Face — repo=%s file=%s",
            YOLO_HF_REPO,
            resolved_ref,
        )
        return hf_hub_download(
            repo_id=YOLO_HF_REPO,
            filename=resolved_ref,
            token=HF_AUTH_TOKEN or None,
        )

    return resolved_ref


# ── Core Processing Logic ──────────────────────────────────────────────────────

def _run_segmentation(model, image: Image.Image) -> Image.Image:
    """Shared inference path for both RMBG-2.0 and BiRefNet."""
    rgb = image.convert("RGB")
    tensor = _seg_transform(rgb).unsqueeze(0).to(registry.device)

    with torch.no_grad():
        output = model(tensor)
        pred = output[-1] if isinstance(output, (list, tuple)) else output
        mask_tensor = pred.sigmoid().cpu()[0].squeeze()

    mask = transforms.ToPILImage()(mask_tensor).resize(
        rgb.size, Image.Resampling.LANCZOS
    )
    result = rgb.copy().convert("RGBA")
    result.putalpha(compositing.refine_alpha_mask(mask))
    return result


def _remove_background(image: Image.Image) -> tuple[Image.Image, str]:
    """Attempt RMBG-2.0 (primary), falling back to BiRefNet if inference
    raises. Returns the result image and the model used."""
    model, name = registry.active_bg_model()

    try:
        return _run_segmentation(model, image), name
    except Exception as exc:
        if name == "briaai/RMBG-2.0":
            logger.warning(
                "RMBG-2.0 inference failed (%s) — retrying with BiRefNet fallback.", exc
            )
            if not registry._birefnet_ok:
                registry._load_birefnet()
            return _run_segmentation(registry._birefnet, image), "ZhengPeng7/BiRefNet"
        raise


def _detect_vehicle(image_rgb: Image.Image, conf: float = 0.35) -> Optional[dict]:
    """Return the largest detected vehicle bounding box, or None."""
    detector = registry.vehicle_detector
    try:
        results = detector(image_rgb, conf=conf, verbose=False)
    except Exception as exc:
        if registry.active_yolo_role != "primary" or not ENABLE_YOLO_FALLBACK:
            raise
        logger.warning(
            "%s raised during inference: %s. Retrying on the fallback detector.",
            registry.active_yolo, exc,
        )
        registry.load_vehicle_fallback()
        results = registry.vehicle_detector(image_rgb, conf=conf, verbose=False)

    candidates: list[dict] = []

    for result in results:
        for box in result.boxes:
            name = result.names[int(box.cls[0])]
            if name not in VEHICLE_CLASSES:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            candidates.append({
                "class": name,
                "score": float(box.conf[0]),
                "box": {
                    "xmin": int(x1), "ymin": int(y1),
                    "xmax": int(x2), "ymax": int(y2),
                },
                "area": max(0.0, x2 - x1) * max(0.0, y2 - y1),
            })

    return max(candidates, key=lambda v: v["area"]) if candidates else None


def _box_area(box: dict) -> float:
    """Pixel area of a detection box, clamped at zero."""
    return (
        max(0.0, box["xmax"] - box["xmin"])
        * max(0.0, box["ymax"] - box["ymin"])
    )


_FRAME_EDGE_MARGIN_PX = 2


def _vehicle_is_cropped_by_frame(box: dict, image_size: tuple[int, int]) -> bool:
    """Whether a detected vehicle's box was clipped to the edge of the
    photograph, rather than the whole body being in frame."""
    width, height = image_size
    if width <= 0 or height <= 0:
        return False
    return (
        box["xmin"] <= _FRAME_EDGE_MARGIN_PX
        or box["ymin"] <= _FRAME_EDGE_MARGIN_PX
        or box["xmax"] >= width - _FRAME_EDGE_MARGIN_PX
        or box["ymax"] >= height - _FRAME_EDGE_MARGIN_PX
    )


def _crop_with_padding(
    image: Image.Image,
    box: dict,
    padding_ratio: float = 0.08,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crop to the vehicle bounding box with proportional padding, returning
    the crop and the absolute pixel coordinates used."""
    w, h = image.size
    bx1, by1, bx2, by2 = (
        box["xmin"], box["ymin"], box["xmax"], box["ymax"]
    )
    pad_x = int((bx2 - bx1) * padding_ratio)
    pad_y = int((by2 - by1) * padding_ratio)
    x1 = max(0, bx1 - pad_x)
    y1 = max(0, by1 - pad_y)
    x2 = min(w, bx2 + pad_x)
    y2 = min(h, by2 + pad_y)
    return image.crop((x1, y1, x2, y2)), (x1, y1, x2, y2)


def _box_in_crop(box: dict, coords: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """A detection box, expressed in the pixel coordinates of the crop taken
    around it by `_crop_with_padding`."""
    crop_x1, crop_y1, _, _ = coords
    return (
        box["xmin"] - crop_x1, box["ymin"] - crop_y1,
        box["xmax"] - crop_x1, box["ymax"] - crop_y1,
    )


def _detect_plates(image_rgba: Image.Image) -> list[dict]:
    """Run YOLOS plate detector and return raw detection dicts above threshold."""
    detections = registry.plate_detector(image_rgba.convert("RGB"))
    return [d for d in detections if d["score"] > PLATE_CONFIDENCE]


def _detect_plate_zone_stickers(
    crop: Image.Image, vehicle_box: tuple[float, float, float, float]
) -> list[dict]:
    """A second, colour-only pass over the same crop `_detect_plates` runs on,
    for something in the plate mount that doesn't look like a real plate."""
    vx1, vy1, vx2, vy2 = vehicle_box
    vx1, vy1 = max(0, int(vx1)), max(0, int(vy1))
    vx2, vy2 = min(crop.width, int(vx2)), min(crop.height, int(vy2))
    vehicle_w, vehicle_h = vx2 - vx1, vy2 - vy1
    if vehicle_w <= 0 or vehicle_h <= 0:
        return []

    zx1 = vx1 + round(vehicle_w * PLATE_ZONE_X_RATIO[0])
    zx2 = vx1 + round(vehicle_w * PLATE_ZONE_X_RATIO[1])
    zy1 = vy1 + round(vehicle_h * PLATE_ZONE_Y_RATIO[0])
    zy2 = vy1 + round(vehicle_h * PLATE_ZONE_Y_RATIO[1])
    if zx2 <= zx1 or zy2 <= zy1:
        return []

    zone = np.array(crop.convert("RGB"))[zy1:zy2, zx1:zx2]
    hsv = cv2.cvtColor(zone, cv2.COLOR_RGB2HSV)
    saturated = (hsv[:, :, 1] >= PLATE_ZONE_MIN_SATURATION).astype(np.uint8)

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        saturated, connectivity=8
    )
    detections: list[dict] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < PLATE_ZONE_MIN_AREA_PX:
            continue
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if w <= 0 or h <= 0:
            continue
        extent = area / (w * h)
        if extent < PLATE_ZONE_MIN_EXTENT:
            continue
        if w < vehicle_w * PLATE_ZONE_MIN_WIDTH_RATIO:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        detections.append({
            "score": 1.0,
            "box": {
                "xmin": zx1 + x, "ymin": zy1 + y,
                "xmax": zx1 + x + w, "ymax": zy1 + y + h,
            },
        })
    return detections


def _plate_coverage(cutout: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of the box that lands on opaque pixels of the vehicle cutout."""
    x1, y1, x2, y2 = box
    alpha = np.array(cutout.convert("RGBA").getchannel("A"), dtype=np.uint8)
    region = alpha[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float(np.count_nonzero(region > 128) / region.size)


_MIN_SEGMENTATION_COVERAGE: float = float(os.getenv("SEGMENTATION_MIN_COVERAGE", "0.35"))


def _segmentation_coverage(cutout: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of `box` that survived background removal as opaque pixels."""
    x1, y1, x2, y2 = box
    alpha = np.array(cutout.convert("RGBA").getchannel("A"), dtype=np.uint8)
    region = alpha[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float(np.count_nonzero(region > 128) / region.size)


def _segmentation_dropped_the_vehicle(
    cutout: Image.Image, vehicle_box_in_crop: tuple[int, int, int, int]
) -> bool:
    """True when background removal kept too little of the detected vehicle
    box opaque to trust the result."""
    return _segmentation_coverage(cutout, vehicle_box_in_crop) < _MIN_SEGMENTATION_COVERAGE


def _filter_plates(
    plates: list[dict],
    vehicle_area: float,
    cutout: Optional[Image.Image] = None,
    angle: Optional[str] = None,
) -> list[dict]:
    """Reject detections that are not plausibly a licence plate."""
    if angle in PLATE_INVISIBLE_ANGLES:
        if plates:
            logger.info(
                "Plate filter rejected all %d detection(s) — angle=%r cannot "
                "show a plate face-on",
                len(plates), angle,
            )
        return []

    kept: list[dict] = []

    for plate in plates:
        b = plate["box"]
        x1, y1 = int(b["xmin"]), int(b["ymin"])
        x2, y2 = int(b["xmax"]), int(b["ymax"])
        width, height = x2 - x1, y2 - y1

        if width <= 0 or height <= 0:
            continue

        aspect = width / height
        if not PLATE_MIN_ASPECT <= aspect <= PLATE_MAX_ASPECT:
            logger.info(
                "Plate rejected — aspect %.2f outside %.2f–%.2f (score=%.2f)",
                aspect, PLATE_MIN_ASPECT, PLATE_MAX_ASPECT, plate["score"],
            )
            continue

        if vehicle_area > 0 and (width * height) / vehicle_area > PLATE_MAX_AREA_RATIO:
            logger.info(
                "Plate rejected — %.1f%% of the vehicle, limit %.1f%% (score=%.2f)",
                100 * (width * height) / vehicle_area,
                100 * PLATE_MAX_AREA_RATIO,
                plate["score"],
            )
            continue

        if cutout is not None:
            coverage = _plate_coverage(cutout, (x1, y1, x2, y2))
            if coverage < PLATE_MIN_COVERAGE:
                logger.info(
                    "Plate rejected — only %.0f%% on the vehicle, needs %.0f%% "
                    "(score=%.2f)",
                    100 * coverage, 100 * PLATE_MIN_COVERAGE, plate["score"],
                )
                continue

        kept.append(plate)

    if len(kept) != len(plates):
        logger.info("Plate filter kept %d of %d detections", len(kept), len(plates))

    return kept


_brand_plate_overlay_cache: Optional[Image.Image] = None
_brand_plate_overlay_loaded: bool = False


def _brand_plate_overlay() -> Optional[Image.Image]:
    """The standing overlay `process()` passes to `_apply_plate_treatment` for
    every job, when `PLATE_BRAND_LOGO_ENABLED` is on."""
    global _brand_plate_overlay_cache, _brand_plate_overlay_loaded
    if not PLATE_BRAND_LOGO_ENABLED:
        return None
    if _brand_plate_overlay_loaded:
        return _brand_plate_overlay_cache

    _brand_plate_overlay_loaded = True
    try:
        _brand_plate_overlay_cache = Image.open(PLATE_BRAND_LOGO_PATH).convert("RGBA")
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        logging.getLogger("autopivot").warning(
            "PLATE_BRAND_LOGO_ENABLED is set but the overlay at %r could not "
            "be loaded (%s) — falling back to PLATE_TREATMENT=%r.",
            PLATE_BRAND_LOGO_PATH, exc, PLATE_TREATMENT,
        )
        _brand_plate_overlay_cache = None
    return _brand_plate_overlay_cache


def _apply_plate_treatment(
    image_rgba: Image.Image,
    plates: list[dict],
    plate_overlay: Optional[Image.Image] = None,
) -> Image.Image:
    """Apply treatment to each detected licence plate region using OpenCV."""
    arr = np.array(image_rgba, dtype=np.uint8)

    for p in plates:
        b = p["box"]
        x1 = max(0, int(b["xmin"]) - PLATE_BOX_PADDING)
        y1 = max(0, int(b["ymin"]) - PLATE_BOX_PADDING)
        x2 = min(arr.shape[1], int(b["xmax"]) + PLATE_BOX_PADDING)
        y2 = min(arr.shape[0], int(b["ymax"]) + PLATE_BOX_PADDING)

        region_w = x2 - x1
        region_h = y2 - y1

        if region_w <= 0 or region_h <= 0:
            continue

        if plate_overlay is not None:
            overlay_resized = plate_overlay.convert("RGBA").resize(
                (region_w, region_h), Image.Resampling.LANCZOS
            )
            overlay_arr = np.array(overlay_resized, dtype=np.float32)

            alpha = overlay_arr[:, :, 3:4] / 255.0
            base_region = arr[y1:y2, x1:x2].astype(np.float32)

            blended_rgb = (
                overlay_arr[:, :, :3] * alpha
                + base_region[:, :, :3] * (1.0 - alpha)
            ).clip(0, 255).astype(np.uint8)

            blended_alpha = np.maximum(
                base_region[:, :, 3],
                overlay_arr[:, :, 3],
            ).clip(0, 255).astype(np.uint8)

            arr[y1:y2, x1:x2, :3] = blended_rgb
            arr[y1:y2, x1:x2, 3] = blended_alpha
        else:
            arr[y1:y2, x1:x2, :3] = _obscure_region(arr[y1:y2, x1:x2, :3])

    return Image.fromarray(arr, "RGBA")


def _obscure_region(region: np.ndarray) -> np.ndarray:
    """Destroy the contents of an RGB region beyond recovery."""
    height, width = region.shape[:2]
    if height <= 0 or width <= 0:
        return region

    if PLATE_TREATMENT == "white":
        return np.full_like(region, 255)

    small_w = max(1, min(PLATE_MOSAIC_WIDTH, width))
    small_h = max(1, round(small_w * height / width))
    small = cv2.resize(region, (small_w, small_h), interpolation=cv2.INTER_AREA)

    if PLATE_TREATMENT == "pixelate":
        return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)

    blown_up = cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)
    kernel = max(3, (max(width, height) // 8) | 1)
    return cv2.GaussianBlur(blown_up, (kernel, kernel), 0)


_classifier_warned = False


def _classify(image: Image.Image) -> Optional[classification.Classification]:
    """What this photograph is of, or None if nothing could look at it."""
    global _classifier_warned

    if not CLASSIFY_IMAGES:
        return None
    try:
        return classification.classify(image)
    except Exception as exc:
        if not _classifier_warned:
            logger.warning(
                "Image classification is unavailable, so photographs will be "
                "processed without it: %s", exc, exc_info=True,
            )
            _classifier_warned = True
        return None


def _place_on_backdrop(
    cutout: Image.Image,
    background: Optional[Image.Image],
    original_size: tuple[int, int],
    coords: tuple[int, int, int, int],
    angle: Optional[str] = None,
    ground_y_ratio: Optional[float] = None,
    angle_confidence: Optional[float] = None,
) -> tuple[Image.Image, dict]:
    """Produce the finished image from a treated cutout: composited onto a
    backdrop when one is given, otherwise pasted back onto a transparent
    canvas at its original position."""
    if background is None:
        canvas = Image.new("RGBA", original_size, (0, 0, 0, 0))
        x1, y1, x2, y2 = coords
        patch = cutout.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
        canvas.paste(patch, (x1, y1), patch.getchannel("A"))
        return canvas, {"backdrop_style": "transparent", "shadow_applied": False}

    preset = compositing.match_studio_backdrop(background)
    if preset is None:
        preset = compositing.DEALER_BACKDROP
        if ground_y_ratio is not None:
            preset = dataclasses.replace(preset, ground_y_ratio=ground_y_ratio)

    return compositing.compose(
        cutout, background, preset, angle=angle, angle_confidence=angle_confidence
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
SERVE_REACT_CLIENT = FRONTEND_DIST.is_dir()


@app.get("/", include_in_schema=False)
async def root() -> Response:
    if SERVE_REACT_CLIENT:
        return FileResponse(FRONTEND_DIST / "index.html")
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "The client has not been built. Run "
                "'npm ci --prefix frontend && npm run build --prefix frontend', "
                "then restart. The API itself is available at /docs."
            )
        },
    )


@app.get("/health", tags=["Observability"])
async def health() -> dict:
    """Liveness + readiness check with per-model status."""
    return {"status": "ready", **registry.health()}


@app.get("/api/status", tags=["Observability"])
async def api_status() -> dict:
    return {
        "status": "online",
        "models": {
            "vehicle": f"YOLO ({registry.active_yolo})",
            "background_primary": "briaai/RMBG-2.0",
            "background_fallback": "ZhengPeng7/BiRefNet",
            "plate": "nickmuchi/yolos-small-finetuned-license-plate-detection",
        },
        **registry.health(),
    }


@app.post("/remove-background", tags=["Processing"])
async def api_remove_background(file: UploadFile = File(...)) -> dict:
    """Remove image background using the active model (RMBG-2.0 or BiRefNet fallback)."""
    content = await file.read()
    _validate_upload(file, content)
    image = _open_image(content)

    logger.info(
        "Background removal — file=%s  size=%d B",
        Path(file.filename).name, len(content),
    )

    result, model_used = _remove_background(image)
    return {
        "success": True,
        "processed_image": _encode_png(result),
        "bg_model_used": model_used,
        "background_removed": True,
        "transparency_preserved": True,
    }


@app.post("/process-vehicle", tags=["Processing"])
async def api_process_vehicle(
    file: UploadFile = File(...),
    background: Optional[UploadFile] = File(None),
    plate_overlay: Optional[UploadFile] = File(None),
) -> dict:
    """Full processing pipeline: detect the vehicle, remove the background,
    treat licence plates, then composite onto a backdrop or return transparent."""
    # ── Read uploads ──
    content = await file.read()
    _validate_upload(file, content)
    image = _open_image(content).convert("RGB")

    bg_image      = await _read_optional_image(background)
    plate_img     = await _read_optional_image(plate_overlay)

    logger.info(
        "Full pipeline — file=%s  size=%d B  background=%s  plate_overlay=%s",
        Path(file.filename).name,
        len(content),
        "yes" if bg_image else "no",
        "yes" if plate_img else "no",
    )

    # ── Step 1 & 2: Vehicle detection ──
    vehicle = _detect_vehicle(image)
    if vehicle is None:
        logger.info("No vehicle detected — pipeline aborted")
        return {
            "success": False,
            "vehicle_detected": False,
            "message": "No vehicle detected. Please upload a clear vehicle image.",
        }

    logger.info(
        "Vehicle detected — class=%s  confidence=%.2f",
        vehicle["class"], vehicle["score"],
    )

    # ── Step 3: Background removal (RMBG-2.0 → BiRefNet fallback) ──
    crop, coords = _crop_with_padding(image, vehicle["box"])
    bg_removed, model_used = _remove_background(crop)
    logger.info("Background removed — model=%s", model_used)

    # ── Step 4: Licence plate detection ──
    vehicle_box_in_crop = _box_in_crop(vehicle["box"], coords)
    plates = _detect_plates(crop) + _detect_plate_zone_stickers(crop, vehicle_box_in_crop)
    plates = _filter_plates(plates, _box_area(vehicle["box"]), bg_removed)
    logger.info("Plates detected — count=%d", len(plates))

    # ── Step 5: Plate treatment ──
    bg_removed = _apply_plate_treatment(bg_removed, plates, plate_img)

    # ── Steps 6 & 7: Placement ──
    final, composite_meta = _place_on_backdrop(bg_removed, bg_image, image.size, coords)

    logger.info(
        "Pipeline complete — plates_treated=%d  bg_applied=%s",
        len(plates),
        "custom" if bg_image else "transparent",
    )

    return {
        "success": True,
        "processed_image": _encode_png(final),
        "vehicle_detected": True,
        "vehicle": {
            "class": vehicle["class"],
            "score": round(vehicle["score"], 4),
            "box": vehicle["box"],
        },
        "bg_model_used": model_used,
        "plates_detected": len(plates),
        "plate_treatment": "overlay" if plate_img else PLATE_TREATMENT,
        "background_applied": "custom" if bg_image else "transparent",
        "background_removed": True,
        "transparency_preserved": bg_image is None,
        "detections": [
            {
                "score": round(float(p["score"]), 4),
                "box": {k: int(v) for k, v in p["box"].items()},
            }
            for p in plates
        ],
        **composite_meta,
    }


@app.post("/detect-and-hide", tags=["Processing"])
async def api_detect_and_hide(
    file: UploadFile = File(...),
    plate_overlay: Optional[UploadFile] = File(None),
) -> dict:
    """Detect and treat licence plates only — no background removal or vehicle detection."""
    content = await file.read()
    _validate_upload(file, content)
    image = _open_image(content).convert("RGBA")
    plate_img = await _read_optional_image(plate_overlay)

    logger.info(
        "Plate detection — file=%s  size=%d B  overlay=%s",
        Path(file.filename).name, len(content),
        "yes" if plate_img else "no",
    )

    plates = _filter_plates(_detect_plates(image), 0.0, None)
    if not plates:
        return {
            "success": False,
            "plates_detected": 0,
            "message": "No licence plates detected.",
        }

    result = _apply_plate_treatment(image, plates, plate_img)
    logger.info("Plates treated — count=%d  method=%s",
                len(plates), "overlay" if plate_img else PLATE_TREATMENT)

    return {
        "success": True,
        "plates_detected": len(plates),
        "processed_image": _encode_png(result),
        "plate_treatment": "overlay" if plate_img else PLATE_TREATMENT,
        "transparency_preserved": True,
        "detections": [
            {
                "score": round(float(p["score"]), 4),
                "box": {k: int(v) for k, v in p["box"].items()},
            }
            for p in plates
        ],
    }

@app.post("/extract-images-from-url", tags=["Extract Images from URL"])
async def api_extract_images_from_url(url: str = Body(..., embed=True)) -> dict:
    """Extract images from a URL. Accepts JSON body: {"url": "https://..."}"""
    try:
        result = await url_import.fetch_images(url)
    except url_import.UrlImportError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        logger.exception("URL import failed unexpectedly")
        return {"success": False, "message": f"Unexpected error while fetching images: {exc}"}

    return {
        "success": True,
        "images": [image.as_payload() for image in result.images],
        "note": result.note,
    }


# ── React client (single-page fallback) ────────────────────────────────────────

if SERVE_REACT_CLIENT:
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(spa_path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / spa_path).resolve()
        if (
            spa_path
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

    logger.info("Serving the React client from %s", FRONTEND_DIST)
else:
    logger.info(
        "frontend/dist not found — serving the original demo page at /. "
        "Run 'npm run build --prefix frontend' to serve the React client."
    )


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting AutoPivot — http://%s:%d", HOST, PORT)
    logger.info("Primary BG model  : briaai/RMBG-2.0")
    logger.info("Fallback BG model : ZhengPeng7/BiRefNet")
    logger.info("YOLO model        : %s", YOLO_MODEL_PATH)
    logger.info("Device            : %s", "cuda" if torch.cuda.is_available() else "cpu")
    uvicorn.run(
        "autopivot_backend:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )
