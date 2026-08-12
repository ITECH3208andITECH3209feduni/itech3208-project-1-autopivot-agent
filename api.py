"""AutoPivot FastAPI layer. Validates uploads, exposes processing routes, serves the frontend, and formats API errors."""

from __future__ import annotations

import base64
import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from config import Settings, settings
from errors import AppError
from model_registry import ModelRegistry, registry
from pipeline_service import PipelineResult, VehiclePipelineService, pipeline

logger = logging.getLogger("autopivot.api")
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


class PipelineProtocol(Protocol):
    def process_vehicle(
        self, image, background=None, plate_overlay=None, background_style=None
    ) -> PipelineResult: ...
    def remove_background(self, image, background=None, background_style=None) -> PipelineResult: ...
    def detect_and_hide(self, image, plate_overlay=None) -> PipelineResult: ...


def error_payload(code: str, message: str, status: int) -> dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "error": {"code": code, "message": message, "status": status},
    }


def validate_upload(content: bytes, content_type: str | None, config: Settings) -> None:
    if content_type not in config.allowed_content_types:
        raise AppError(
            "UNSUPPORTED_MEDIA_TYPE",
            "Only JPG, PNG and WEBP images are supported.",
            415,
        )
    if len(content) > config.max_file_bytes:
        raise AppError(
            "FILE_TOO_LARGE",
            f"File size exceeds the {config.max_file_mb} MB limit.",
            413,
        )


def decode_image(content: bytes) -> Image.Image:
    try:
        check = Image.open(io.BytesIO(content))
        check.verify()
        return Image.open(io.BytesIO(content))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError("INVALID_IMAGE", "The uploaded file is not a valid image.", 400) from exc


def encode_image(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


async def read_image(upload: UploadFile, config: Settings) -> Image.Image:
    content = await upload.read()
    validate_upload(content, upload.content_type, config)
    return decode_image(content)


async def read_optional(upload: UploadFile | None, config: Settings) -> Image.Image | None:
    if upload is None or not upload.filename:
        return None
    return await read_image(upload, config)


def result_payload(result: PipelineResult) -> dict[str, Any]:
    return {"success": True, "processed_image": encode_image(result.image), **result.metadata}


def processing_routes(service: PipelineProtocol, config: Settings) -> APIRouter:
    router = APIRouter(tags=["Processing"])

    @router.post("/process-vehicle")
    async def process_vehicle(
        file: UploadFile = File(...),
        background: UploadFile | None = File(None),
        plate_overlay: UploadFile | None = File(None),
        background_style: str | None = Form(None),
    ) -> dict[str, Any]:
        image = await read_image(file, config)
        background_image = await read_optional(background, config)
        plate_image = await read_optional(plate_overlay, config)
        if background_style is None:
            result = service.process_vehicle(image, background_image, plate_image)
        else:
            result = service.process_vehicle(
                image,
                background_image,
                plate_image,
                background_style,
            )
        return result_payload(result)

    @router.post("/remove-background")
    async def remove_background(
        file: UploadFile = File(...),
        background: UploadFile | None = File(None),
        background_style: str | None = Form(None),
    ) -> dict[str, Any]:
        image = await read_image(file, config)
        background_image = await read_optional(background, config)
        if background_style is None:
            result = service.remove_background(image, background_image)
        else:
            result = service.remove_background(image, background_image, background_style)
        return result_payload(result)

    @router.post("/detect-and-hide")
    async def detect_and_hide(
        file: UploadFile = File(...),
        plate_overlay: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        image = await read_image(file, config)
        plate_image = await read_optional(plate_overlay, config)
        return result_payload(service.detect_and_hide(image, plate_image))

    return router


def create_app(
    config: Settings = settings,
    models: ModelRegistry = registry,
    service: PipelineProtocol = pipeline,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        models.startup()
        yield

    app = FastAPI(title="AutoPivot", version="3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.response())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload("INVALID_REQUEST", "The request is missing required data.", 422),
        )

    @app.exception_handler(Exception)
    async def unknown_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_SERVER_ERROR", "An unexpected server error occurred.", 500),
        )

    routes = processing_routes(service, config)
    app.include_router(routes)
    app.include_router(processing_routes(service, config), prefix=config.api_v1_prefix)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ready", **models.health()}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return {
            "status": "online",
            "api_version": "v1",
            "models": {
                "background_primary": config.rmbg_model_id,
                "background_fallback": config.birefnet_model_id,
                "vehicle_primary": config.yolo_primary_model_path,
                "vehicle_fallback": config.yolo_fallback_model_path,
                "plate": config.plate_model_id,
            },
            **models.health(),
        }

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(config.base_dir / "index.html")

    @app.get("/style.css", include_in_schema=False)
    async def css() -> FileResponse:
        return FileResponse(config.base_dir / "style.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return FileResponse(config.base_dir / "app.js", media_type="application/javascript")

    asset_directory = str(config.base_dir / "assets")
    app.mount(
        "/static/assets",
        StaticFiles(directory=asset_directory),
        name="assets",
    )
    app.mount(
        "/assets",
        StaticFiles(directory=asset_directory),
        name="assets-direct",
    )
    return app


app = create_app()
