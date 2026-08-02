# AutoPivot Backend
# Developed by Vadim Rudoi, Akhanda Bhandari and Suraj Purella

from __future__ import annotations

import base64
import io
import logging
import logging.config
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from huggingface_hub import get_token, hf_hub_download, login
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from ultralytics import YOLO

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import socket
import httpx
import asyncio
import base64
import ipaddress
import mimetypes
import re


# ── Configuration ──────────────────────────────────────────────────────────────
# Fixed by Vadim Rudoi — all hardcoded values replaced with environment-based config

HF_TOKEN: str       = os.getenv("HF_TOKEN", "")
HF_AUTH_TOKEN: str  = HF_TOKEN or (get_token() or "")
HOST: str           = os.getenv("HOST", "0.0.0.0")
PORT: int           = int(os.getenv("PORT", 8000))
MAX_FILE_MB: int    = int(os.getenv("MAX_FILE_MB", 20))
MAX_FILE_BYTES: int = MAX_FILE_MB * 1024 * 1024

# Fixed by Vadim Rudoi — YOLO model path is now configurable via environment
# variable instead of being hardcoded to a non-existent filename.
YOLO_HF_REPO: str    = os.getenv("YOLO_HF_REPO", "Ultralytics/YOLO26")
YOLO_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "yolo26n.pt")

# Fixed by Vadim Rudoi — wildcard "*" + allow_credentials=True is an invalid
# CORS combo rejected by all modern browsers. Origins are now explicit and
# credentials are disabled (tokens belong in Authorization headers for an API).
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
VEHICLE_CLASSES: frozenset[str] = frozenset(
    {"car", "truck", "bus", "motorcycle"}
)

BASE_DIR = Path(__file__).resolve().parent

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

# ---------------------------------------------------------------------------
# Config image extraction from URL
# ---------------------------------------------------------------------------

MAX_IMAGES = 20                    # matches the frontend's MAX_FILES
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # matches the frontend's MAX_FILE_SIZE (10MB)
MIN_IMAGE_BYTES = 2 * 1024          # skip tiny tracking pixels / spacer gifs
MAX_PAGE_BYTES = 5 * 1024 * 1024    # don't try to parse enormous HTML pages
FETCH_TIMEOUT = 10.0                # seconds, per HTTP request
CONCURRENT_DOWNLOADS = 6

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AutoPivotImageImporter/1.0)",
    "Accept": "text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5",
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

        self._device: str = "cuda" if torch.cuda.is_available() else "cpu"

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

    def _load_vehicle(self) -> None:
        """
        Fixed by Vadim Rudoi — YOLO model filename is configurable via the
        YOLO_MODEL_PATH environment variable instead of being hardcoded.
        """
        logger.info("Loading YOLO vehicle detector — %s", YOLO_MODEL_PATH)
        try:
            model_path = _resolve_yolo_model_path(YOLO_MODEL_PATH)
            self._vehicle = YOLO(model_path)
            self._vehicle_ok = True
            self.active_yolo = str(model_path)
            logger.info("YOLO loaded: %s", model_path)
        except Exception as exc:
            logger.critical(
                "YOLO model '%s' failed to load: %s",
                YOLO_MODEL_PATH, exc, exc_info=True,
            )
            raise RuntimeError(
                f"YOLO model unavailable (configured={YOLO_MODEL_PATH}): {exc}"
            ) from exc

    def _load_plates(self) -> None:
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
            "vehicle_detector_loaded": self._vehicle_ok,
            "plate_detector_loaded": self._plates_ok,
        }


registry = ModelRegistry()

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

    logger.info(
        "AutoPivot ready — device=%s  active_bg_model=%s  yolo=%s",
        registry.device,
        registry.health()["active_bg_model"],
        registry.active_yolo,
    )
    yield
    logger.info("AutoPivot shutting down")


# ── FastAPI Application ────────────────────────────────────────────────────────

app = FastAPI(
    title="AutoPivot",
    description=(
        "Vehicle background removal, detection, and licence-plate treatment API. "
        "Developed by Vadim Rudoi."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Fixed by Vadim Rudoi — correct CORS config (explicit origins, no credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Fixed by Vadim Rudoi — individual FileResponse routes replaced with StaticFiles
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")


# ── Global Exception Handler ───────────────────────────────────────────────────
# Developed by Vadim Rudoi

@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method, request.url.path, exc, exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred."},
    )


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
    result = rgb.copy().convert("RGBA")
    result.putalpha(mask)
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
    """Return the largest detected vehicle bounding box, or None."""
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


def _composite_onto_original(
    original: Image.Image,
    processed_crop: Image.Image,
    coords: tuple[int, int, int, int],
) -> Image.Image:
    """
    Paste the background-removed crop back onto a transparent canvas that
    matches the full original image dimensions.

    Fixed by Vadim Rudoi — the previous implementation returned the raw crop,
    discarding all spatial context and producing output at crop resolution.
    """
    x1, y1, x2, y2 = coords
    canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
    patch = processed_crop.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
    canvas.paste(patch, (x1, y1), mask=patch.split()[3])
    return canvas


def _detect_plates(image_rgba: Image.Image) -> list[dict]:
    """Run YOLOS plate detector and return raw detection dicts above threshold."""
    detections = registry.plate_detector(image_rgba.convert("RGB"))
    return [d for d in detections if d["score"] > 0.3]


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
    • If no overlay is provided: paint a solid white rectangle over the plate
      (GDPR-compliant blanking).
    """
    arr = np.array(image_rgba, dtype=np.uint8)

    for p in plates:
        b = p["box"]
        x1 = max(0, int(b["xmin"]) - 5)
        y1 = max(0, int(b["ymin"]) - 5)
        x2 = min(arr.shape[1], int(b["xmax"]) + 5)
        y2 = min(arr.shape[0], int(b["ymax"]) + 5)

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
            # Blank the plate with an opaque white rectangle
            cv2.rectangle(arr, (x1, y1), (x2, y2), (255, 255, 255, 255), -1)

    return Image.fromarray(arr, "RGBA")


def _apply_background(
    foreground_rgba: Image.Image,
    background: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Developed by Vadim Rudoi — composite the vehicle (RGBA foreground with
    transparent background) onto a custom background image.

    • If background is provided: resize it to match the foreground canvas and
      alpha-composite foreground on top.
    • If not provided: return the transparent RGBA foreground as-is (the
      frontend or caller handles the transparent PNG).
    """
    if background is None:
        return foreground_rgba

    bg = background.convert("RGBA").resize(
        foreground_rgba.size, Image.Resampling.LANCZOS
    )
    # PIL alpha_composite: dst first, src on top
    return Image.alpha_composite(bg, foreground_rgba)


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/style.css", include_in_schema=False)
async def stylesheet() -> FileResponse:
    return FileResponse(BASE_DIR / "style.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
async def javascript() -> FileResponse:
    return FileResponse(BASE_DIR / "app.js", media_type="application/javascript")


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
      Step 5  YOLOS licence-plate detection.
      Step 6  Plate treatment via OpenCV:
                • plate_overlay provided  → resize and alpha-composite onto plate
                • no plate_overlay        → blank with white rectangle
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

    # ── Step 4: Composite back onto full canvas ──
    # Fixed by Vadim Rudoi — previously the raw crop was returned, losing all
    # spatial context and producing output at crop resolution only.
    full_result = _composite_onto_original(image, bg_removed, coords)

    # ── Step 5: Licence plate detection ──
    plates = _detect_plates(full_result)
    logger.info("Plates detected — count=%d", len(plates))

    # ── Step 6: Plate treatment ──
    full_result = _apply_plate_treatment(full_result, plates, plate_img)

    # ── Step 7: Background compositing ──
    final = _apply_background(full_result, bg_image)

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
        "plate_treatment": "overlay" if plate_img else "blanked",
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

    plates = _detect_plates(image)
    if not plates:
        return {
            "success": False,
            "plates_detected": 0,
            "message": "No licence plates detected.",
        }

    result = _apply_plate_treatment(image, plates, plate_img)
    logger.info("Plates treated — count=%d  method=%s",
                len(plates), "overlay" if plate_img else "blanked")

    return {
        "success": True,
        "plates_detected": len(plates),
        "processed_image": _encode_png(result),
        "plate_treatment": "overlay" if plate_img else "blanked",
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
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"success": False, "message": "Please provide a valid http:// or https:// URL."}

    if not _is_safe_host(parsed.hostname):
        return {"success": False, "message": "That URL can't be fetched."}

    try:
        async with httpx.AsyncClient(
            headers=REQUEST_HEADERS,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=CONCURRENT_DOWNLOADS),
        ) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                return {"success": False, "message": f"Could not reach that URL: {exc}"}

            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"The page responded with status {response.status_code}.",
                }

            # A redirect could have taken us somewhere unsafe — re-check the final host.
            final_host = urlparse(str(response.url)).hostname
            if not _is_safe_host(final_host):
                return {"success": False, "message": "That URL can't be fetched."}

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()

            # Case 1: the URL is itself a direct image.
            if content_type in ALLOWED_IMAGE_TYPES:
                entry = _build_image_entry(str(response.url), response.content, content_type, index=0)
                return {"success": True, "images": [entry] if entry else []}

            # Case 2: treat it as an HTML page and scan for images.
            if "html" not in content_type:
                return {
                    "success": False,
                    "message": "That URL doesn't look like a webpage or a supported image.",
                }

            if len(response.content) > MAX_PAGE_BYTES:
                return {"success": False, "message": "That page is too large to scan."}

            candidate_urls = _extract_image_urls(response.text, base_url=str(response.url))
            if not candidate_urls:
                return {"success": True, "images": []}

            # Fetch a few extra beyond MAX_IMAGES since some will fail/be too small.
            candidate_urls = candidate_urls[: MAX_IMAGES * 2]
            semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

            async def fetch_one(img_url: str, index: int):
                img_host = urlparse(img_url).hostname
                if not _is_safe_host(img_host):
                    return None
                async with semaphore:
                    try:
                        img_resp = await client.get(img_url)
                    except httpx.HTTPError:
                        return None
                    if img_resp.status_code >= 400:
                        return None
                    img_ctype = img_resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if img_ctype not in ALLOWED_IMAGE_TYPES:
                        return None
                    if not (MIN_IMAGE_BYTES <= len(img_resp.content) <= MAX_IMAGE_BYTES):
                        return None
                    return _build_image_entry(img_url, img_resp.content, img_ctype, index)

            results = await asyncio.gather(*[fetch_one(u, i) for i, u in enumerate(candidate_urls)])
            images = [entry for entry in results if entry][:MAX_IMAGES]

            return {"success": True, "images": images}

    except Exception as exc:  # surface a clean message instead of a raw 500
        return {"success": False, "message": f"Unexpected error while fetching images: {exc}"}









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



# ---------------------------------------------------------------------------
# Helpers image extraction from URL
# ---------------------------------------------------------------------------

def _is_safe_host(hostname: str | None) -> bool:
    """Reject hostnames that resolve to private/loopback/link-local/reserved IPs (SSRF guard)."""
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def _extract_image_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []

    def add(candidate: str | None):
        if not candidate:
            return
        candidate = candidate.strip()
        if not candidate or candidate.startswith("data:"):
            return
        absolute = urljoin(base_url, candidate)
        p = urlparse(absolute)
        if p.scheme not in ("http", "https") or absolute in seen:
            return
        seen.add(absolute)
        urls.append(absolute)

    for img in soup.find_all("img"):
        add(img.get("src"))
        add(img.get("data-src"))       # common lazy-load attributes
        add(img.get("data-lazy-src"))
        srcset = img.get("srcset")
        if srcset:
            add(srcset.split(",")[0].strip().split(" ")[0])

    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            add(srcset.split(",")[0].strip().split(" ")[0])

    if not urls:
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            add(og_image["content"])

    return urls


def _build_image_entry(source_url: str, content: bytes, content_type: str, index: int) -> dict | None:
    if not content:
        return None
    ext = ALLOWED_IMAGE_TYPES.get(content_type) or mimetypes.guess_extension(content_type) or ".jpg"
    filename = _filename_from_url(source_url, fallback_index=index, ext=ext)
    return {
        "filename": filename,
        "content_type": content_type,
        "data": base64.b64encode(content).decode("ascii"),
    }


def _filename_from_url(url: str, fallback_index: int, ext: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if not name or "." not in name:
        name = f"url-image-{fallback_index + 1}{ext}"
    return name