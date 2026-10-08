from __future__ import annotations

from api.env import load_environment

load_environment()

import base64  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import logging.config  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
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
from PIL.PngImagePlugin import PngInfo
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from ultralytics import YOLO

import classification
import compositing
import vehicle_isolation
import elevation
from api import processing, url_import
from api.app import create_app
from api.config import BASE_DIR, HOST, PORT
from device_utils import as_torch_device, device_info, select_device


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

PLATE_CONFIDENCE: float = float(os.getenv("PLATE_CONFIDENCE", "0.25"))
PLATE_UPSCALE: float = float(os.getenv("PLATE_UPSCALE", "2.0"))
PLATE_UPSCALE_MAX_SIDE: int = 3200
PLATE_BOX_PADDING: int = int(os.getenv("PLATE_BOX_PADDING", "5"))

PLATE_MIN_ASPECT: float = float(os.getenv("PLATE_MIN_ASPECT", "1.2"))
PLATE_MAX_ASPECT: float = float(os.getenv("PLATE_MAX_ASPECT", "6.5"))

PLATE_MAX_AREA_RATIO: float = float(os.getenv("PLATE_MAX_AREA_RATIO", "0.12"))

PLATE_MIN_COVERAGE: float = float(os.getenv("PLATE_MIN_COVERAGE", "0.55"))

PLATE_TREATMENTS: frozenset[str] = frozenset({"blur", "pixelate", "white"})
PLATE_TREATMENT: str = os.getenv("PLATE_TREATMENT", "blur").strip().lower()
if PLATE_TREATMENT not in PLATE_TREATMENTS:
    logging.getLogger("autopivot").warning(
        "PLATE_TREATMENT=%r is not one of %s — using 'blur'.",
        PLATE_TREATMENT, ", ".join(sorted(PLATE_TREATMENTS)),
    )
    PLATE_TREATMENT = "blur"

PLATE_MOSAIC_WIDTH: int = int(os.getenv("PLATE_MOSAIC_WIDTH", "8"))

PLATE_INVISIBLE_ANGLES: frozenset[str] = frozenset({"side"})
PLATE_SIDE_SKIP_MIN_CONFIDENCE: float = float(os.getenv("PLATE_SIDE_SKIP_MIN_CONFIDENCE", "1.01"))

PLATE_RETRY_SCALE: float = float(os.getenv("PLATE_RETRY_SCALE", "2.0"))
PLATE_RETRY_TOP_RATIO: float = 0.35
PLATE_RETRY_CONFIDENCE: float = float(os.getenv("PLATE_RETRY_CONFIDENCE", "0.20"))

PLATE_ZONE_MIN_SATURATION: int = int(os.getenv("PLATE_ZONE_MIN_SATURATION", "80"))
PLATE_ZONE_X_RATIO: tuple[float, float] = (0.05, 0.95)
PLATE_ZONE_Y_RATIO: tuple[float, float] = (0.45, 0.93)
PLATE_ZONE_MIN_EXTENT: float = float(os.getenv("PLATE_ZONE_MIN_EXTENT", "0.70"))
PLATE_ZONE_MIN_AREA_PX: int = int(os.getenv("PLATE_ZONE_MIN_AREA_PX", "120"))
PLATE_ZONE_MIN_WIDTH_RATIO: float = float(os.getenv("PLATE_ZONE_MIN_WIDTH_RATIO", "0.12"))
PLATE_ZONE_MAX_WIDTH_RATIO: float = 0.45
PLATE_ZONE_ASPECT: tuple[float, float] = (1.4, 6.5)
PLATE_ZONE_RED_CENTRE_BAND: tuple[float, float] = (0.35, 0.65)

PLATE_BRAND_LOGO_ENABLED: bool = os.getenv(
    "PLATE_BRAND_LOGO_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
PLATE_BRAND_LOGO_PATH: str = os.getenv(
    "PLATE_BRAND_LOGO_PATH", str(BASE_DIR / "assets" / "autopivot-plate-logo.png")
)

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
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
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
        self._birefnet: Optional[AutoModelForImageSegmentation] = None
        self._birefnet_ok = False

        self._vehicle: Optional[YOLO] = None
        self._plates = None
        self._vehicle_ok = False
        self._plates_ok = False

        self.active_yolo: str = "none"
        self.active_yolo_role: str = "none"

        self._device: str = select_device(torch)
        self._device_info: dict = device_info(torch, self._device)
        logger.info(
            "Selected inference device: %s (%s)",
            self._device,
            self._device_info["accelerator"],
        )

        self._vehicle_lock = threading.RLock()
        self._plates_lock = threading.RLock()
        self._bg_lock = threading.RLock()

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

    def _load_birefnet(self) -> None:
        """Developed by Vadim Rudoi — load BiRefNet, the background removal model."""
        with self._bg_lock:
            if self._birefnet_ok:
                return

            logger.info("Loading background model — ZhengPeng7/BiRefNet")
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

    def load_vehicle_fallback(self) -> None:
        """Contributed by Suraj Purella (Autopivot-refactored-pipeline) — load the
        secondary detector.
        """
        if not ENABLE_YOLO_FALLBACK:
            raise RuntimeError("YOLO fallback is disabled by ENABLE_YOLO_FALLBACK")

        logger.info("Loading fallback vehicle detector — %s", YOLO_FALLBACK_MODEL_PATH)
        self._vehicle = YOLO(YOLO_FALLBACK_MODEL_PATH)
        self._vehicle_ok = True
        self.active_yolo = str(YOLO_FALLBACK_MODEL_PATH)
        self.active_yolo_role = "fallback"
        logger.info("Fallback detector loaded: %s", YOLO_FALLBACK_MODEL_PATH)

    def _load_vehicle(self) -> None:
        """Fixed by Vadim Rudoi — YOLO model filename is configurable via the
        YOLO_MODEL_PATH environment variable instead of being hardcoded.
        """
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
                    device=as_torch_device(torch, self._device),
                )
                self._plates_ok = True
                logger.info("YOLOS plate detector loaded")
            except Exception as exc:
                logger.critical("Plate detector failed to load: %s", exc, exc_info=True)
                raise RuntimeError(f"Plate detector unavailable: {exc}") from exc

    def active_bg_model(self):
        """Return the background removal model and its identifier."""
        if self._birefnet_ok:
            return self._birefnet, "ZhengPeng7/BiRefNet"
        raise RuntimeError(
            "No background removal model is loaded. "
            "Check startup logs for a BiRefNet error."
        )

    def health(self) -> dict:
        active_bg = "ZhengPeng7/BiRefNet" if self._birefnet_ok else "none"

        return {
            "device": self._device,
            "device_info": self._device_info,
            "active_bg_model": active_bg,
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
        placement: Optional[processing.BackdropPlacement] = None,
        backdrop_for_angle=None,
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

        edges = _frame_edges_touched(vehicle["box"], source.size)
        top_only = edges == {"top"}
        if edges and not top_only:
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message=_VEHICLE_CROPPED_BY_FRAME,
            )

        crop, coords = _crop_with_padding(source, vehicle["box"])
        bg_removed, model_used = _remove_background(crop)

        if top_only and not (
            coords[1] == 0 and _only_a_thin_part_touches_the_top(
                bg_removed, vehicle["box"]["xmax"] - vehicle["box"]["xmin"])
        ):
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message=_VEHICLE_CROPPED_BY_FRAME,
            )

        vehicle_box_in_crop = _box_in_crop(vehicle["box"], coords)
        if _segmentation_dropped_the_vehicle(bg_removed, vehicle_box_in_crop):
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=classified.kind if classified else None,
                kind_confidence=classified.kind_confidence if classified else None,
                message=_SEGMENTATION_INCOMPLETE,
            )

        bg_removed = _isolate_main_vehicle(crop, bg_removed, vehicle_box_in_crop)

        angle = classified.angle if classified else None
        angle_confidence = classified.angle_confidence if classified else None

        plates = _detect_plates(crop) + _detect_plate_zone_stickers(crop, vehicle_box_in_crop)
        plates = _filter_plates(
            plates, _box_area(vehicle["box"]), bg_removed,
            angle=angle, angle_confidence=angle_confidence,
        )
        if not any(p["score"] < 1.0 for p in plates):
            closer = _filter_plates(
                _detect_plates_closer(crop, vehicle_box_in_crop),
                _box_area(vehicle["box"]), bg_removed,
                angle=angle, angle_confidence=angle_confidence,
            )
            if closer:
                logger.info("Plate found on the closer second pass (%d)", len(closer))
            plates += closer
        plates = _one_plate_per_end(plates)
        brand_overlay = _brand_plate_overlay()
        bg_removed = _apply_plate_treatment(bg_removed, plates, brand_overlay)

        estimated = _estimate_elevation(bg_removed, angle)

        backdrop_id_used = None
        if background is not None and backdrop_for_angle is not None:
            choice = backdrop_for_angle(angle)
            if choice is not None:
                background, placement = choice.image, choice.placement
                backdrop_id_used = choice.backdrop_id
                logger.info("Using backdrop %s for a %s shot", backdrop_id_used, angle)

        background_image = _open_image(background) if background else None
        final, placement_info = _place_on_backdrop(
            bg_removed, background_image, source.size, coords, angle=angle,
            placement=placement, estimated=estimated,
            angle_confidence=angle_confidence,
        )
        placement_info = placement_info or {}
        for warning in placement_info.get("placement_warnings", []):
            logger.warning("Placement review: %s", warning)

        buffer = io.BytesIO()
        png_info = PngInfo()
        png_info.add_text("autopivot_compositor", compositing.COMPOSITOR_REVISION)
        try:
            png_info.add_text("autopivot_placement", json.dumps(placement_info, default=str))
        except (TypeError, ValueError):
            pass
        final.save(buffer, format="PNG", pnginfo=png_info)

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
            camera_elevation_deg=estimated.degrees if estimated else None,
            elevation_confidence=estimated.confidence if estimated else None,
            elevation_method=estimated.method if estimated else None,
            image_kind=classified.kind if classified else None,
            kind_confidence=classified.kind_confidence if classified else None,
            backdrop_id_used=backdrop_id_used,
            review_note=" ".join(placement_info.get("placement_warnings", [])) or None,
        )


# ── Application Lifespan ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Compositor version: %s (placement engine: %s)",
                compositing.COMPOSITOR_REVISION, compositing.PLACEMENT_ENGINE)
    if HF_TOKEN:
        try:
            login(token=HF_TOKEN)
            logger.info("HuggingFace authentication successful")
        except Exception as exc:
            logger.warning("HuggingFace login failed: %s", exc)
    elif HF_AUTH_TOKEN:
        logger.info("Using HuggingFace token from local hf auth login cache")
    else:
        logger.info(
            "HF_TOKEN is not set — downloading YOLO26 anonymously, subject to "
            "Hugging Face's unauthenticated rate limit. No model this pipeline "
            "uses requires authentication."
        )

    registry._load_birefnet()

    processing.set_processor(PipelineProcessor())
    processing.resume_unfinished_jobs()

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
    """Safely decode image bytes."""
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
    """Developed by Vadim Rudoi — inference path for BiRefNet, which produces a
    single-channel sigmoid output used directly as an alpha mask.
    """
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
    """Developed by Vadim Rudoi — run BiRefNet."""
    model, name = registry.active_bg_model()
    return _run_segmentation(model, image), name


VEHICLE_SEG_ENABLED: bool = os.getenv("VEHICLE_SEG_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on"}
VEHICLE_SEG_MODEL: str = os.getenv("VEHICLE_SEG_MODEL", "yolo11m-seg.pt")
_COCO_VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck
_vehicle_seg_lock = threading.Lock()
_vehicle_seg_model = None
_vehicle_seg_failed = False


def _vehicle_segmenter():
    global _vehicle_seg_model, _vehicle_seg_failed
    if not VEHICLE_SEG_ENABLED or _vehicle_seg_failed:
        return None
    with _vehicle_seg_lock:
        if _vehicle_seg_model is None and not _vehicle_seg_failed:
            try:
                _vehicle_seg_model = YOLO(VEHICLE_SEG_MODEL)
                logger.info("Loaded vehicle outline model %s", VEHICLE_SEG_MODEL)
            except Exception as exc:  # offline, bad file, ...
                _vehicle_seg_failed = True
                logger.warning("Vehicle outline model unavailable (%s); skipping "
                               "other-car removal", exc)
    return _vehicle_seg_model


def _isolate_main_vehicle(
    crop: Image.Image, cutout: Image.Image, vehicle_box: tuple[int, int, int, int],
) -> Image.Image:
    """Clear any part of the cutout that belongs to another car."""
    model = _vehicle_segmenter()
    if model is None:
        return cutout
    try:
        result = model.predict(
            np.array(crop.convert("RGB"))[:, :, ::-1], classes=_COCO_VEHICLE_CLASSES,
            conf=0.20, retina_masks=True, verbose=False, device=registry.device,
        )[0]
        if result.masks is None or len(result.masks) < 2:
            return cutout
        masks = [m > 0.5 for m in result.masks.data.cpu().numpy()]
        masks = [m for m in masks if m.shape == (cutout.height, cutout.width)]
    except Exception as exc:
        logger.warning("Other-car check skipped: %s", exc)
        return cutout
    cleaned, removed = vehicle_isolation.remove_other_vehicles(cutout, masks, vehicle_box)
    if removed:
        logger.info("Removed %d px of another vehicle from the cutout", removed)
    return cleaned


def _detect_vehicle(image_rgb: Image.Image, conf: float = 0.35) -> Optional[dict]:
    """Return the largest detected vehicle bounding box, or None."""
    detector = registry.vehicle_detector
    try:
        results = detector(
            image_rgb,
            conf=conf,
            verbose=False,
            device=registry.device,
        )
    except Exception as exc:
        if registry.active_yolo_role != "primary" or not ENABLE_YOLO_FALLBACK:
            raise
        logger.warning(
            "%s raised during inference: %s. Retrying on the fallback detector.",
            registry.active_yolo, exc,
        )
        registry.load_vehicle_fallback()
        results = registry.vehicle_detector(
            image_rgb,
            conf=conf,
            verbose=False,
            device=registry.device,
        )

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


def _frame_edges_touched(box: dict, image_size: tuple[int, int]) -> set[str]:
    """Which edges of the photograph the vehicle's box runs into."""
    width, height = image_size
    if width <= 0 or height <= 0:
        return set()
    edges = set()
    if box["xmin"] <= _FRAME_EDGE_MARGIN_PX:
        edges.add("left")
    if box["ymin"] <= _FRAME_EDGE_MARGIN_PX:
        edges.add("top")
    if box["xmax"] >= width - _FRAME_EDGE_MARGIN_PX:
        edges.add("right")
    if box["ymax"] >= height - _FRAME_EDGE_MARGIN_PX:
        edges.add("bottom")
    return edges


def _vehicle_is_cropped_by_frame(box: dict, image_size: tuple[int, int]) -> bool:
    """Whether a detected vehicle's box was clipped to the edge of the photograph,
    rather than the whole body being in frame.
    """
    return bool(_frame_edges_touched(box, image_size))


_TOP_EDGE_ALLOWED_SPAN = 0.15


def _only_a_thin_part_touches_the_top(cutout: Image.Image, vehicle_width: float) -> bool:
    """True when the cutout meets the top of the photo only over a narrow span (an
    aerial, a fin, a roof-rack tip) - the body itself is in frame.
    """
    alpha = np.asarray(cutout.convert("RGBA").getchannel("A"))
    rows = alpha[: _FRAME_EDGE_MARGIN_PX + 2] > 128
    columns = np.flatnonzero(rows.any(axis=0))
    if columns.size == 0:
        return True
    return (columns[-1] - columns[0] + 1) <= max(1.0, vehicle_width) * _TOP_EDGE_ALLOWED_SPAN


def _box_in_crop(box: dict, coords: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """A detection box, expressed in the pixel coordinates of the crop taken around it
    by `_crop_with_padding`.
    """
    crop_x1, crop_y1, _, _ = coords
    return (
        box["xmin"] - crop_x1, box["ymin"] - crop_y1,
        box["xmax"] - crop_x1, box["ymax"] - crop_y1,
    )


def _crop_with_padding(
    image: Image.Image,
    box: dict,
    padding_ratio: float = 0.08,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crop to the vehicle bounding box with proportional padding."""
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


def _plate_box_iou(a: dict, b: dict) -> float:
    ax1, ay1, ax2, ay2 = (a["box"][k] for k in ("xmin", "ymin", "xmax", "ymax"))
    bx1, by1, bx2, by2 = (b["box"][k] for k in ("xmin", "ymin", "xmax", "ymax"))
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _detect_plates(image_rgba: Image.Image) -> list[dict]:
    """Run the YOLOS plate detector at 1x and at PLATE_UPSCALE, merge the two."""
    image = image_rgba.convert("RGB")
    found = [d for d in registry.plate_detector(image) if d["score"] > PLATE_CONFIDENCE]

    scale = max(1.0, PLATE_UPSCALE)
    if scale > 1.0 and max(image.size) * scale <= PLATE_UPSCALE_MAX_SIDE:
        enlarged = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        try:
            extra = registry.plate_detector(enlarged)
        except Exception as exc:  # the 1x pass already succeeded
            logger.warning("Enlarged plate-detection pass skipped: %s", exc)
            extra = []
        for d in extra:
            if d["score"] <= PLATE_CONFIDENCE:
                continue
            b = d["box"]
            found.append({
                **d,
                "score": float(d["score"]),
                "box": {
                    "xmin": max(0, round(b["xmin"] / scale)),
                    "ymin": max(0, round(b["ymin"] / scale)),
                    "xmax": min(image.width, round(b["xmax"] / scale)),
                    "ymax": min(image.height, round(b["ymax"] / scale)),
                },
            })

    kept: list[dict] = []
    for candidate in sorted(found, key=lambda d: d["score"], reverse=True):
        if all(_plate_box_iou(candidate, k) < 0.5 for k in kept):
            kept.append(candidate)
    return kept


def _detect_plates_closer(
    crop: Image.Image, vehicle_box: tuple[float, float, float, float]
) -> list[dict]:
    """Run the plate detector again on the lower part of the vehicle, enlarged."""
    vx1, vy1, vx2, vy2 = (int(v) for v in vehicle_box)
    vx1, vy1 = max(0, vx1), max(0, vy1)
    vx2, vy2 = min(crop.width, vx2), min(crop.height, vy2)
    if vx2 - vx1 < 20 or vy2 - vy1 < 20:
        return []
    top = vy1 + int((vy2 - vy1) * PLATE_RETRY_TOP_RATIO)
    region = crop.convert("RGB").crop((vx1, top, vx2, vy2))
    scale = PLATE_RETRY_SCALE
    region = region.resize(
        (max(1, round(region.width * scale)), max(1, round(region.height * scale))),
        Image.Resampling.LANCZOS,
    )
    found = []
    for d in registry.plate_detector(region):
        if d["score"] <= PLATE_RETRY_CONFIDENCE:
            continue
        b = d["box"]
        found.append({
            "score": float(d["score"]),
            "box": {
                "xmin": vx1 + int(b["xmin"] / scale), "ymin": top + int(b["ymin"] / scale),
                "xmax": vx1 + int(b["xmax"] / scale), "ymax": top + int(b["ymax"] / scale),
            },
        })
    return found


def _detect_plate_zone_stickers(
    crop: Image.Image, vehicle_box: tuple[float, float, float, float]
) -> list[dict]:
    """A second, colour-only pass over the same crop `_detect_plates` runs on, for
    something in the plate mount that doesn't look like a real plate.
    """
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
        if area / (w * h) < PLATE_ZONE_MIN_EXTENT:
            continue
        if w < vehicle_w * PLATE_ZONE_MIN_WIDTH_RATIO:
            continue
        if w > vehicle_w * PLATE_ZONE_MAX_WIDTH_RATIO:
            continue
        if not PLATE_ZONE_ASPECT[0] <= w / h <= PLATE_ZONE_ASPECT[1]:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        component = _labels[y:y + h, x:x + w] == label
        hues = hsv[y:y + h, x:x + w, 0][component]
        reddish = float(np.mean((hues <= 10) | (hues >= 170))) if hues.size else 0.0
        centre = (zx1 + x + w / 2 - vx1) / vehicle_w
        if reddish > 0.5 and not (
            PLATE_ZONE_RED_CENTRE_BAND[0] <= centre <= PLATE_ZONE_RED_CENTRE_BAND[1]
        ):
            continue
        detections.append({
            "score": 1.0,
            "box": {
                "xmin": zx1 + x, "ymin": zy1 + y,
                "xmax": zx1 + x + w, "ymax": zy1 + y + h,
            },
        })
    return detections


_MIN_SEGMENTATION_COVERAGE: float = float(os.getenv("SEGMENTATION_MIN_COVERAGE", "0.35"))


def _segmentation_coverage(cutout: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of `box` that survived background removal as opaque pixels."""
    x1, y1, x2, y2 = (max(0, int(v)) for v in box)
    alpha = np.array(cutout.convert("RGBA").getchannel("A"), dtype=np.uint8)
    region = alpha[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float(np.count_nonzero(region > 128) / region.size)


def _segmentation_dropped_the_vehicle(
    cutout: Image.Image, vehicle_box_in_crop: tuple[int, int, int, int]
) -> bool:
    """True when background removal kept too little of the detected vehicle box opaque
    to trust the result.
    """
    return _segmentation_coverage(cutout, vehicle_box_in_crop) < _MIN_SEGMENTATION_COVERAGE


_brand_plate_overlay_cache: Optional[Image.Image] = None
_brand_plate_overlay_loaded: bool = False


def _brand_plate_overlay() -> Optional[Image.Image]:
    """The standing overlay `process()` passes to `_apply_plate_treatment` for every
    job, when `PLATE_BRAND_LOGO_ENABLED` is on.
    """
    global _brand_plate_overlay_cache, _brand_plate_overlay_loaded
    if not PLATE_BRAND_LOGO_ENABLED:
        return None
    if _brand_plate_overlay_loaded:
        return _brand_plate_overlay_cache

    _brand_plate_overlay_loaded = True
    try:
        _brand_plate_overlay_cache = Image.open(PLATE_BRAND_LOGO_PATH).convert("RGBA")
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        logger.warning(
            "PLATE_BRAND_LOGO_ENABLED is set but the overlay at %r could not "
            "be loaded (%s) — falling back to PLATE_TREATMENT=%r.",
            PLATE_BRAND_LOGO_PATH, exc, PLATE_TREATMENT,
        )
        _brand_plate_overlay_cache = None
    return _brand_plate_overlay_cache


def _plate_coverage(cutout: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of the box that lands on opaque pixels of the vehicle cutout."""
    x1, y1, x2, y2 = box
    alpha = np.array(cutout.convert("RGBA").getchannel("A"), dtype=np.uint8)
    region = alpha[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float(np.count_nonzero(region > 128) / region.size)


PLATE_SECOND_MIN_SCORE: float = float(os.getenv("PLATE_SECOND_MIN_SCORE", "0.70"))


def _one_plate_per_end(plates: list[dict]) -> list[dict]:
    """Keep the strongest detector plate, plus any other the detector is very sure of;
    plate-mount stickers (score 1.0) are kept as they are.
    """
    stickers = [p for p in plates if p["score"] >= 1.0]
    detected = sorted((p for p in plates if p["score"] < 1.0),
                      key=lambda p: p["score"], reverse=True)
    if len(detected) <= 1:
        return plates
    kept = [detected[0]] + [p for p in detected[1:] if p["score"] >= PLATE_SECOND_MIN_SCORE]
    dropped = len(detected) - len(kept)
    if dropped:
        logger.info("Ignored %d weaker plate detection(s) - likely badge lettering", dropped)
    return kept + stickers


def _filter_plates(
    plates: list[dict],
    vehicle_area: float,
    cutout: Optional[Image.Image] = None,
    angle: Optional[str] = None,
    angle_confidence: Optional[float] = None,
) -> list[dict]:
    """Reject detections that are not plausibly a licence plate."""
    if (
        angle in PLATE_INVISIBLE_ANGLES
        and angle_confidence is not None
        and angle_confidence >= PLATE_SIDE_SKIP_MIN_CONFIDENCE
    ):
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


def _apply_plate_treatment(
    image_rgba: Image.Image,
    plates: list[dict],
    plate_overlay: Optional[Image.Image] = None,
) -> Image.Image:
    """Developed by Vadim Rudoi — apply treatment to each detected licence plate region
    using OpenCV:
    """
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


def _estimate_elevation(
    cutout: Image.Image, angle: Optional[str]
) -> Optional[elevation.ElevationEstimate]:
    """Where the camera was for this photograph, or None if it could not be worked out
    at all.
    """
    try:
        return elevation.estimate_elevation(cutout, angle)
    except Exception as exc:
        logger.warning(
            "Camera elevation could not be estimated, so this photograph is "
            "processed without one: %s", exc, exc_info=True,
        )
        return None


def _place_on_backdrop(
    cutout: Image.Image,
    background: Optional[Image.Image],
    original_size: tuple[int, int],
    coords: tuple[int, int, int, int],
    angle: Optional[str] = None,
    placement: Optional[processing.BackdropPlacement] = None,
    estimated: Optional[elevation.ElevationEstimate] = None,
    angle_confidence: Optional[float] = None,
) -> tuple[Image.Image, dict]:
    """Produce the finished image from a treated cutout."""
    if background is None:
        canvas = Image.new("RGBA", original_size, (0, 0, 0, 0))
        x1, y1, x2, y2 = coords
        patch = cutout.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
        canvas.paste(patch, (x1, y1), patch.getchannel("A"))
        return canvas, {"backdrop_style": "transparent", "shadow_applied": False}

    placement = placement or processing.BackdropPlacement()
    preset = compositing.dealer_preset(
        horizon_y_ratio=placement.horizon_y_ratio,
        floor_top_y_ratio=placement.floor_top_y_ratio,
    )

    elevation_deg = None
    if (
        estimated is not None
        and estimated.method in elevation.MEASURED_METHODS
        and estimated.confidence >= elevation.MIN_USEFUL_CONFIDENCE
    ):
        elevation_deg = estimated.degrees

    return compositing.compose(
        cutout, background, preset, angle=angle,
        angle_confidence=angle_confidence, elevation_deg=elevation_deg,
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
    return {"status": "ready", "compositor_revision": compositing.COMPOSITOR_REVISION,
            **registry.health()}


@app.get("/api/status", tags=["Observability"])
async def api_status() -> dict:
    return {
        "status": "online",
        "compositor_revision": compositing.COMPOSITOR_REVISION,
        "placement_engine": compositing.PLACEMENT_ENGINE,
        "models": {
            "vehicle": f"YOLO ({registry.active_yolo})",
            "background": "ZhengPeng7/BiRefNet",
            "plate": "nickmuchi/yolos-small-finetuned-license-plate-detection",
        },
        **registry.health(),
    }


@app.post("/remove-background", tags=["Processing"])
async def api_remove_background(file: UploadFile = File(...)) -> dict:
    """Remove image background using BiRefNet. No vehicle detection or plate treatment
    is performed.
    """
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
    """Full processing pipeline — Developed by Vadim Rudoi:"""
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

    crop, coords = _crop_with_padding(image, vehicle["box"])
    bg_removed, model_used = _remove_background(crop)
    logger.info("Background removed — model=%s", model_used)

    plates = _detect_plates(crop)
    plates = _filter_plates(plates, _box_area(vehicle["box"]), bg_removed)
    logger.info("Plates detected — count=%d", len(plates))

    bg_removed = _apply_plate_treatment(bg_removed, plates, plate_img)

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
    """Detect and treat licence plates only — no background removal or vehicle
    detection.
    """
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
    except Exception as exc:  # a clean message beats a raw 500
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
    logger.info("Background model  : ZhengPeng7/BiRefNet")
    logger.info("YOLO model        : %s", YOLO_MODEL_PATH)
    logger.info(
        "Device            : %s (%s)",
        registry.device,
        registry.health()["device_info"]["accelerator"],
    )
    uvicorn.run(
        "autopivot_backend:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )

