# AutoPivot Backend
# Developed by Vadim Rudoi, Akhanda Bhandari and Suraj Purella

from __future__ import annotations

import base64
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

import compositing
from api import processing, url_import
from api.app import create_app
from api.config import BASE_DIR, HOST, PORT


# ── Configuration ──────────────────────────────────────────────────────────────
# Fixed by Vadim Rudoi — all hardcoded values replaced with environment-based config

# HOST, PORT, ALLOWED_ORIGINS, BASE_DIR and .env loading now live in
# api/config.py so the light API can be served without importing this module.

HF_TOKEN: str       = os.getenv("HF_TOKEN", "")
HF_AUTH_TOKEN: str  = HF_TOKEN or (get_token() or "")
MAX_FILE_MB: int    = int(os.getenv("MAX_FILE_MB", 20))
MAX_FILE_BYTES: int = MAX_FILE_MB * 1024 * 1024

# Fixed by Vadim Rudoi — YOLO model path is now configurable via environment
# variable instead of being hardcoded to a non-existent filename.
YOLO_HF_REPO: str    = os.getenv("YOLO_HF_REPO", "Ultralytics/YOLO26")
YOLO_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "yolo26n.pt")

# Contributed by Suraj Purella (Autopivot-refactored-pipeline) — a second
# detector to fall back to. YOLO26 is served from a Hugging Face repo, so a
# rate limit or a withdrawn file takes vehicle detection down with it and the
# whole pipeline stops. YOLO11 ships with ultralytics and needs no repo.
YOLO_FALLBACK_MODEL_PATH: str = os.getenv("YOLO_FALLBACK_MODEL_PATH", "yolo11n.pt")
ENABLE_YOLO_FALLBACK: bool = os.getenv(
    "ENABLE_YOLO_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}

# ── Licence plate handling ──
# A misplaced mask is worse than no mask: a white rectangle painted over empty
# background is visible damage to a photograph a dealer intends to publish,
# whereas an unmasked plate is a photograph that simply still needs a person.
# These bounds exist to make the second failure the likely one.
PLATE_CONFIDENCE: float = float(os.getenv("PLATE_CONFIDENCE", "0.30"))
PLATE_BOX_PADDING: int = int(os.getenv("PLATE_BOX_PADDING", "5"))

# AU plates are ~372×134 mm (2.8:1) and NZ ~360×130 mm (2.8:1); European
# slimline runs to about 4.7:1 and motorcycle plates are nearer 1.3:1. Viewing
# angle only ever compresses the width, so the bounds are deliberately wide —
# they are here to reject boxes that are nothing like a plate, not to grade
# borderline ones.
PLATE_MIN_ASPECT: float = float(os.getenv("PLATE_MIN_ASPECT", "1.2"))
PLATE_MAX_ASPECT: float = float(os.getenv("PLATE_MAX_ASPECT", "6.5"))

# A plate is a small part of a car. Anything above this is a panel or a window.
PLATE_MAX_AREA_RATIO: float = float(os.getenv("PLATE_MAX_AREA_RATIO", "0.12"))

# Fraction of the box that must land on the vehicle cutout rather than on
# transparent background. This is what rejects a plate detected in empty space.
PLATE_MIN_COVERAGE: float = float(os.getenv("PLATE_MIN_COVERAGE", "0.55"))

# blur | pixelate | white
PLATE_TREATMENT: str = os.getenv("PLATE_TREATMENT", "blur").strip().lower()

# Width in pixels the plate is downsampled to before being scaled back up.
# The downsample is what destroys the characters; the upsample only decides
# whether the result reads as a blur or as a mosaic.
PLATE_MOSAIC_WIDTH: int = int(os.getenv("PLATE_MOSAIC_WIDTH", "8"))

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
# Developed by Vadim Rudoi

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
# Both RMBG-2.0 and BiRefNet use the same ImageNet normalisation and 1024×1024
# input resolution, so one transform covers both models.

_SEG_SIZE = (1024, 1024)
_seg_transform = transforms.Compose([
    transforms.Resize(_SEG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

# ── Model Registry ─────────────────────────────────────────────────────────────
# Developed by Vadim Rudoi — centralised registry with:
#   • RMBG-2.0 as primary background removal model
#   • BiRefNet as automatic fallback if RMBG-2.0 is unavailable
#   • Independent health tracking per model
#   • Lazy loading for vehicle and plate detectors


class ModelRegistry:
    """Centralised model registry with lazy loading and per-model health tracking."""

    def __init__(self) -> None:
        # Background removal — primary + fallback
        self._rmbg: Optional[AutoModelForImageSegmentation] = None
        self._birefnet: Optional[AutoModelForImageSegmentation] = None
        self._rmbg_ok = False
        self._birefnet_ok = False

        # Detection models (lazy)
        self._vehicle: Optional[YOLO] = None
        self._plates = None
        self._vehicle_ok = False
        self._plates_ok = False

        self.active_yolo: str = "none"
        self.active_yolo_role: str = "none"

        self._device: str = "cuda" if torch.cuda.is_available() else "cpu"

        # Contributed by Suraj Purella (Autopivot-refactored-pipeline) — one
        # lock per lazily-loaded model. Sync FastAPI endpoints run in a thread
        # pool and run_listing_jobs walks a batch, so two requests can reach an
        # unloaded detector at the same moment. Without these, both threads see
        # `not _vehicle_ok`, both call YOLO(), and the second overwrites the
        # first mid-inference.
        self._vehicle_lock = threading.RLock()
        self._plates_lock = threading.RLock()
        # Background models load at startup, which is single-threaded, but
        # _remove_background also promotes BiRefNet mid-request when RMBG-2.0
        # raises during inference. That path is concurrent.
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
        """
        Developed by Vadim Rudoi — load BRIA RMBG-2.0 as the primary
        background removal model. Requires a HuggingFace token from an account
        that has accepted the BRIA license on https://huggingface.co/briaai/RMBG-2.0
        """
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
        """
        Developed by Vadim Rudoi — load BiRefNet as the fallback background
        removal model, used whenever RMBG-2.0 is unavailable.
        """
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
        """
        Contributed by Suraj Purella (Autopivot-refactored-pipeline) — load the
        secondary detector. Kept public because _detect_vehicle also calls it
        when YOLO26 loads cleanly but then raises during inference.
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
        """
        Fixed by Vadim Rudoi — YOLO model filename is configurable via the
        YOLO_MODEL_PATH environment variable instead of being hardcoded.

        Falls back to YOLO11 — contributed by Suraj Purella.
        """
        with self._vehicle_lock:
            # Re-checked inside the lock: a thread that blocked here may have
            # been waiting on the very load it was about to start.
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
# Wraps the seven-step pipeline in the interface api/processing.py expects, so
# job orchestration, storage and status tracking stay free of any ML import.


class PipelineProcessor:
    """Runs the full pipeline over raw bytes and reports what it found."""

    def process(
        self, image: bytes, background: Optional[bytes]
    ) -> processing.ProcessOutcome:
        source = _open_image(image).convert("RGB")

        vehicle = _detect_vehicle(source)
        if vehicle is None:
            # A correct run that produced nothing usable — recorded as needing
            # review rather than as a failure.
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                message="No vehicle detected in this photograph.",
            )

        crop, coords = _crop_with_padding(source, vehicle["box"])
        bg_removed, model_used = _remove_background(crop)

        # Plates are found on the cropped original rather than the finished
        # composite. At 3000-odd pixels wide the plate is a sliver of the frame
        # and the detector's own resize leaves it a few pixels across; on the
        # crop it occupies far more of the input. The crop is also ordinary
        # photographic pixels, which is what the detector was trained on — a
        # cutout floating on transparency is not.
        plates = _detect_plates(crop)
        plates = _filter_plates(plates, _box_area(vehicle["box"]), bg_removed)
        # Treated here, before the compositor rescales the cutout to fit the
        # scene: after that, coordinates taken from the crop no longer apply.
        bg_removed = _apply_plate_treatment(bg_removed, plates, None)

        background_image = _open_image(background) if background else None
        final, _ = _place_on_backdrop(bg_removed, background_image, source.size, coords)

        buffer = io.BytesIO()
        final.save(buffer, format="PNG")

        return processing.ProcessOutcome(
            image_png=buffer.getvalue(),
            vehicle_detected=True,
            plates_detected=len(plates),
            # No overlay is offered through the listings flow yet, so detected
            # plates are obscured by whatever PLATE_TREATMENT selects.
            plate_treatment=PLATE_TREATMENT if plates else "none",
            model_used=model_used,
            # detected_angle and angle_confidence stay unset: nothing computes a
            # shot angle yet, and inventing one would put a number on screen
            # that no measurement supports.
        )


# ── Application Lifespan ───────────────────────────────────────────────────────
# Developed by Vadim Rudoi — startup sequence:
#   1. HuggingFace authentication (required for RMBG-2.0 and BiRefNet)
#   2. Attempt RMBG-2.0 (primary) — failure is non-fatal, logged as WARNING
#   3. If RMBG-2.0 failed, load BiRefNet (fallback) — failure IS fatal
#   4. Detection models load lazily on first request


@asynccontextmanager
async def lifespan(app: FastAPI):
    if HF_TOKEN:
        try:
            login(token=HF_TOKEN)
            logger.info("HuggingFace authentication successful")
        except Exception as exc:
            # Fixed by Vadim Rudoi — previously crashed unconditionally on auth
            # failure. We log the error and continue; the downstream model load
            # will surface the 401 with a clear message if the token was the
            # only issue.
            logger.warning("HuggingFace login failed: %s", exc)
    elif HF_AUTH_TOKEN:
        logger.info("Using HuggingFace token from local hf auth login cache")
    else:
        # Fixed by Vadim Rudoi — silent skip replaced with actionable warning.
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

    # Hands the pipeline to the job orchestrator in api/processing.py. Until
    # this runs, POST /api/listings/{id}/process answers 503 rather than
    # queueing work no model can execute.
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

# CORS, the global exception handler and the auth routes are configured by the
# factory, so the light API (uvicorn api.app:app) and this full application
# behave identically on everything that is not vehicle processing.
app = create_app(
    lifespan=lifespan,
    description=(
        "Vehicle background removal, detection, and licence-plate treatment API. "
        "Developed by Vadim Rudoi."
    ),
)

# The /static mount is gone with the vanilla page that needed it. It originally
# published the entire project root — serving .env, the backend source and the
# database models to any caller — and was then narrowed to assets/ for the demo
# image. Nothing serves that image now, so the whole mount goes: files under
# assets/ stay in the repository but are no longer exposed over HTTP. Everything
# a signed-in user needs is served through /api/files, which checks ownership.


# ── Validation Helpers ─────────────────────────────────────────────────────────
# Developed by Vadim Rudoi — previously there was no validation at all.
# Any payload was passed straight to PIL and produced opaque 500 errors.


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
    """
    Safely decode image bytes.

    PIL's Image.verify() is destructive (it closes the internal stream), so we
    open the buffer twice — once to verify integrity, once to return a usable
    object. Corrupt or non-image payloads surface as HTTP 400.
    """
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
    """
    Resolve a YOLO model reference to a local file path that Ultralytics can load.

    Plain YOLO26 filenames are downloaded from Hugging Face into the local cache;
    explicit local paths are used as-is.
    """
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
    """
    Developed by Vadim Rudoi — shared inference path for both RMBG-2.0 and
    BiRefNet. Both models use the same ImageNet normalisation and produce a
    single-channel sigmoid output that is used directly as an alpha mask.
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
    # Mask cleanup contributed by Suraj Purella (Auto_pivot_Scaling). The mask
    # is produced at 1024x1024 and stretched over a photograph several times
    # that wide, which leaves a soft fringe of background clinging to the
    # silhouette — invisible against white, obvious against a studio floor.
    result = rgb.copy().convert("RGBA")
    result.putalpha(compositing.refine_alpha_mask(mask))
    return result


def _remove_background(image: Image.Image) -> tuple[Image.Image, str]:
    """
    Developed by Vadim Rudoi — attempt RMBG-2.0 (primary). If it raises at
    inference time (e.g. a runtime error after a successful load), fall back to
    BiRefNet automatically and log a warning. Returns the result image and the
    name of the model that was actually used.
    """
    model, name = registry.active_bg_model()

    # Primary attempt
    try:
        return _run_segmentation(model, image), name
    except Exception as exc:
        # Only falls through to fallback if the primary was RMBG-2.0
        if name == "briaai/RMBG-2.0":
            logger.warning(
                "RMBG-2.0 inference failed (%s) — retrying with BiRefNet fallback.", exc
            )
            if not registry._birefnet_ok:
                registry._load_birefnet()
            return _run_segmentation(registry._birefnet, image), "ZhengPeng7/BiRefNet"
        raise


def _detect_vehicle(image_rgb: Image.Image, conf: float = 0.35) -> Optional[dict]:
    """
    Return the largest detected vehicle bounding box, or None.

    Inference-time fallback contributed by Suraj Purella
    (Autopivot-refactored-pipeline): a model that loaded cleanly can still
    raise on a particular image, and that used to fail the job outright.
    """
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


def _crop_with_padding(
    image: Image.Image,
    box: dict,
    padding_ratio: float = 0.08,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """
    Crop to the vehicle bounding box with proportional padding.
    Returns the crop and the absolute pixel coordinates used, so the processed
    result can be composited back onto the original canvas.
    """
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


def _detect_plates(image_rgba: Image.Image) -> list[dict]:
    """Run YOLOS plate detector and return raw detection dicts above threshold."""
    detections = registry.plate_detector(image_rgba.convert("RGB"))
    return [d for d in detections if d["score"] > PLATE_CONFIDENCE]


def _plate_coverage(cutout: Image.Image, box: tuple[int, int, int, int]) -> float:
    """
    Fraction of the box that lands on opaque pixels of the vehicle cutout.

    The detector runs on the original photograph, so it can fire on something
    in the background — a sign, a wheelie bin, a reflection. After background
    removal that area is transparent, which is a far more reliable signal than
    the detector's own confidence.
    """
    x1, y1, x2, y2 = box
    alpha = np.array(cutout.convert("RGBA").getchannel("A"), dtype=np.uint8)
    region = alpha[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float(np.count_nonzero(region > 128) / region.size)


def _filter_plates(
    plates: list[dict],
    vehicle_area: float,
    cutout: Optional[Image.Image] = None,
) -> list[dict]:
    """
    Reject detections that are not plausibly a licence plate.

    YOLOS-small is permissive and its false positives are expensive: each one
    paints an obscuration over part of the photograph that has no plate in it.
    Geometry and cutout coverage are cheap, independent evidence.
    """
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
    """
    Developed by Vadim Rudoi — apply treatment to each detected licence plate
    region using OpenCV:

    • If plate_overlay is provided: resize the overlay to the plate bounding box
      and alpha-composite it onto the vehicle image, preserving any transparency
      in the overlay itself.
    • If no overlay is provided: obscure the plate according to PLATE_TREATMENT.
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
            # Resize the overlay image to exactly fit the plate bounding box
            overlay_resized = plate_overlay.convert("RGBA").resize(
                (region_w, region_h), Image.Resampling.LANCZOS
            )
            overlay_arr = np.array(overlay_resized, dtype=np.float32)

            # Per-pixel alpha compositing via OpenCV
            # Formula: out = overlay_rgb * alpha + base_rgb * (1 - alpha)
            alpha = overlay_arr[:, :, 3:4] / 255.0
            base_region = arr[y1:y2, x1:x2].astype(np.float32)

            blended_rgb = (
                overlay_arr[:, :, :3] * alpha
                + base_region[:, :, :3] * (1.0 - alpha)
            ).clip(0, 255).astype(np.uint8)

            # Preserve the maximum alpha between overlay and original
            blended_alpha = np.maximum(
                base_region[:, :, 3],
                overlay_arr[:, :, 3],
            ).clip(0, 255).astype(np.uint8)

            arr[y1:y2, x1:x2, :3] = blended_rgb
            arr[y1:y2, x1:x2, 3] = blended_alpha
        else:
            arr[y1:y2, x1:x2, :3] = _obscure_region(arr[y1:y2, x1:x2, :3])
            # Alpha is deliberately left untouched. The white rectangle this
            # replaced forced alpha to 255 across the whole box, so a detection
            # that strayed off the vehicle punched an opaque white block into
            # the transparent background and survived compositing.

    return Image.fromarray(arr, "RGBA")


def _obscure_region(region: np.ndarray) -> np.ndarray:
    """
    Destroy the contents of an RGB region beyond recovery.

    Both modes downsample to PLATE_MOSAIC_WIDTH first, which is what actually
    discards the characters — a Gaussian blur alone is a convolution and can be
    partially inverted. The upsample filter only decides how the result reads:
    NEAREST gives a mosaic, and a smooth interpolation followed by a light blur
    gives something closer to soft focus, which sits better on a listing photo.
    """
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
    # Kernel scales with the box so a plate close to camera is blurred as
    # thoroughly as a distant one, and stays odd as GaussianBlur requires.
    kernel = max(3, (max(width, height) // 8) | 1)
    return cv2.GaussianBlur(blown_up, (kernel, kernel), 0)


def _place_on_backdrop(
    cutout: Image.Image,
    background: Optional[Image.Image],
    original_size: tuple[int, int],
    coords: tuple[int, int, int, int],
) -> tuple[Image.Image, dict]:
    """
    Produce the finished image from a treated cutout.

    With a backdrop, hand off to the compositor: the vehicle is scaled to the
    scene, stood on its ground line, given shadows and colour-matched.

    Without one, fall back to the old behaviour — the cutout returns to its
    place on a transparent canvas the size of the original photograph. There is
    no scene to sit in, so scaling to a fixed canvas would only throw away
    resolution.
    """
    if background is None:
        canvas = Image.new("RGBA", original_size, (0, 0, 0, 0))
        x1, y1, x2, y2 = coords
        patch = cutout.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
        canvas.paste(patch, (x1, y1), patch.getchannel("A"))
        return canvas, {"backdrop_style": "transparent", "shadow_applied": False}

    return compositing.compose(cutout, background, compositing.DEALER_BACKDROP)


# ── Routes ─────────────────────────────────────────────────────────────────────


# The React client is the only interface. The original single-page demo — its
# index.html, style.css and app.js, plus the routes that served them — has been
# removed: the product is a platform with accounts, listings and a backdrop
# library, and keeping a second, unauthenticated interface alongside it meant two
# front doors to maintain and one of them bypassing every access control.
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
SERVE_REACT_CLIENT = FRONTEND_DIST.is_dir()


@app.get("/", include_in_schema=False)
async def root() -> Response:
    if SERVE_REACT_CLIENT:
        return FileResponse(FRONTEND_DIST / "index.html")
    # Said plainly rather than as a 500 from a missing file: this is the first
    # thing anyone sees after forgetting the build step.
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
    """
    Remove image background using the active model (RMBG-2.0 or BiRefNet
    fallback). No vehicle detection or plate treatment is performed.
    """
    content = await file.read()
    _validate_upload(file, content)
    image = _open_image(content)

    # Fixed by Vadim Rudoi — filename sanitised via Path.name to strip any
    # path-traversal characters from untrusted client input before logging.
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
    """
    Full processing pipeline — Developed by Vadim Rudoi:

      Step 1  YOLO vehicle detection — abort early if no vehicle found.
      Step 2  Crop vehicle region with padding.
      Step 3  Background removal via RMBG-2.0 (primary) → BiRefNet (fallback).
      Step 4  Composite background-removed crop back onto full-size canvas.
      Step 4  YOLOS licence-plate detection on the crop, filtered by geometry
              and by how much of each box lands on the vehicle cutout.
      Step 5  Plate treatment via OpenCV:
                • plate_overlay provided  → resize and alpha-composite onto plate
                • no plate_overlay        → obscure per PLATE_TREATMENT
      Step 6  Composite the treated crop back onto a full-size canvas.
      Step 7  Background compositing:
                • background provided  → composite vehicle onto custom background
                • no background        → return transparent PNG

    Accepts three multipart fields:
      file           (required) — vehicle photograph
      background     (optional) — custom background image
      plate_overlay  (optional) — image to apply over detected licence plates
    """
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
    # Run on the cropped original, not the finished composite: the plate is a
    # much larger share of the input, and the pixels are photographic rather
    # than a cutout on transparency.
    plates = _detect_plates(crop)
    plates = _filter_plates(plates, _box_area(vehicle["box"]), bg_removed)
    logger.info("Plates detected — count=%d", len(plates))

    # ── Step 5: Plate treatment ──
    # Before compositing: the cutout is rescaled to fit the scene, after which
    # coordinates measured on the crop no longer apply.
    bg_removed = _apply_plate_treatment(bg_removed, plates, plate_img)

    # ── Steps 6 & 7: Placement ──
    # With a backdrop this scales the vehicle to the scene, stands it on the
    # ground line, lays down shadows and matches its colour to the light —
    # compositing contributed by Suraj Purella (Auto_pivot_Scaling). Without
    # one, the cutout returns to its place on a transparent canvas the size of
    # the original photograph.
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
    """
    Detect and treat licence plates only — no background removal or vehicle
    detection. Accepts an optional plate_overlay image (same OpenCV compositing
    as the full pipeline).
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

    # No vehicle box and no cutout here, so only the shape check applies —
    # passing 0.0 skips the relative-area test rather than rejecting everything.
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
    """
    Extract images from a URL. Accepts JSON body: {"url": "https://..."}

    The fetching and parsing are Akhanda Bhandari's and now live in
    api/url_import.py, shared with the authenticated listing importer at
    POST /api/listings/{id}/images/from-url. This endpoint returns base64 to
    the caller and stores nothing.
    """
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
# Registered last on purpose. Starlette matches routes in registration order, so
# every API route above wins; this only sees what nothing else claimed.
#
# The fallback is what makes a deep link work: /app/vehicles/12 is a client-side
# route with no file behind it, so a refresh has to return index.html and let
# the router sort it out. Without this, reloading any page but "/" 404s.

if SERVE_REACT_CLIENT:
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(spa_path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / spa_path).resolve()
        # A path from the URL must not be able to reach outside the build.
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
