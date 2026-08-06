from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api import create_app
from config import settings
from errors import NoPlateError, NoVehicleError
from model_registry import ModelRegistry
from pipeline_service import PipelineResult, VehiclePipelineService


class FakeModels:
    device = "cpu"

    def startup(self):
        pass

    def health(self):
        return {
            "device": "cpu",
            "active_bg_model": "fake",
            "active_yolo_model": "fake",
        }


class FakeService:
    def process_vehicle(self, image, background=None, plate_overlay=None):
        return PipelineResult(
            image.convert("RGBA"),
            {
                "vehicle_detected": True,
                "vehicle": {
                    "class": "car",
                    "score": 0.9,
                    "box": {"xmin": 0, "ymin": 0, "xmax": 4, "ymax": 4},
                },
                "bg_model_used": "fake/rmbg",
                "plates_detected": 1,
                "plate_treatment": "blanked",
                "background_applied": "transparent",
                "background_removed": True,
                "transparency_preserved": True,
                "detections": [],
            },
        )

    def remove_background(self, image, background=None):
        return PipelineResult(
            image.convert("RGBA"),
            {
                "bg_model_used": "fake/rmbg",
                "background_removed": True,
                "background_applied": "transparent",
                "transparency_preserved": True,
            },
        )

    def detect_and_hide(self, image, plate_overlay=None):
        return PipelineResult(
            image.convert("RGBA"),
            {
                "plates_detected": 1,
                "plate_treatment": "blanked",
                "transparency_preserved": True,
                "detections": [],
            },
        )


class NoVehicleService(FakeService):
    def process_vehicle(self, image, background=None, plate_overlay=None):
        raise NoVehicleError()


class NoPlateService(FakeService):
    def detect_and_hide(self, image, plate_overlay=None):
        raise NoPlateError()


class BrokenService(FakeService):
    def process_vehicle(self, image, background=None, plate_overlay=None):
        raise RuntimeError("private technical detail")


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def post_image(client: TestClient, path: str):
    return client.post(path, files={"file": ("car.png", png_bytes(), "image/png")})


def test_old_and_versioned_routes_work():
    app = create_app(settings, FakeModels(), FakeService())
    with TestClient(app) as client:
        for prefix in ("", "/api/v1"):
            assert post_image(client, prefix + "/process-vehicle").status_code == 200
            assert post_image(client, prefix + "/remove-background").status_code == 200
            assert post_image(client, prefix + "/detect-and-hide").status_code == 200


def test_errors_are_structured():
    app = create_app(settings, FakeModels(), NoVehicleService())
    with TestClient(app) as client:
        response = post_image(client, "/api/v1/process-vehicle")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_VEHICLE_DETECTED"


def test_no_plate_error_is_structured():
    app = create_app(settings, FakeModels(), NoPlateService())
    with TestClient(app) as client:
        response = post_image(client, "/detect-and-hide")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_PLATE_DETECTED"


def test_private_exception_details_are_hidden():
    app = create_app(settings, FakeModels(), BrokenService())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = post_image(client, "/process-vehicle")
    assert response.status_code == 500
    assert "private technical detail" not in response.text


def test_bad_file_types_and_corrupt_images_are_rejected():
    app = create_app(settings, FakeModels(), FakeService())
    with TestClient(app) as client:
        wrong_type = client.post(
            "/remove-background",
            files={"file": ("note.txt", b"hello", "text/plain")},
        )
        corrupt = client.post(
            "/remove-background",
            files={"file": ("bad.png", b"not-image", "image/png")},
        )
    assert wrong_type.status_code == 415
    assert corrupt.status_code == 400


def test_large_file_is_rejected():
    small_limit = replace(settings, max_file_mb=1)
    app = create_app(small_limit, FakeModels(), FakeService())
    with TestClient(app) as client:
        response = client.post(
            "/remove-background",
            files={"file": ("large.png", b"x" * (small_limit.max_file_bytes + 1), "image/png")},
        )
    assert response.status_code == 413


def test_background_fallback(monkeypatch):
    models = ModelRegistry(settings)
    primary = object()
    fallback = object()
    models._rmbg = primary
    models._rmbg_ok = True

    def load_fallback():
        models._birefnet = fallback
        models._birefnet_ok = True

    monkeypatch.setattr(models, "_load_birefnet", load_fallback)

    def run(model, image):
        if model is primary:
            raise RuntimeError("failed")
        return image.convert("RGBA")

    result, name = models.remove_background(Image.new("RGB", (4, 4)), run)
    assert result.mode == "RGBA"
    assert name == settings.birefnet_model_id


def test_yolo_fallback(monkeypatch):
    models = ModelRegistry(settings)

    class BrokenYolo:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("failed")

    class WorkingYolo:
        def __call__(self, *args, **kwargs):
            return []

    models._vehicle = BrokenYolo()
    models._vehicle_ok = True
    models.active_yolo_role = "primary"

    def load_fallback():
        models._vehicle = WorkingYolo()
        models._vehicle_ok = True
        models.active_yolo = settings.yolo_fallback_model_path
        models.active_yolo_role = "fallback"

    monkeypatch.setattr(models, "_load_vehicle_fallback", load_fallback)
    assert models.detect_vehicle(Image.new("RGB", (4, 4)), 0.35) is None
    assert models.active_yolo_role == "fallback"


def test_pipeline_file_has_no_fastapi_import():
    source = open("pipeline_service.py", encoding="utf-8").read()
    assert "fastapi" not in source.lower()


def test_backend_file_is_thin():
    source = open("autopivot_backend.py", encoding="utf-8").read()
    assert "def process_vehicle" not in source
    assert "from api import app" in source


def test_frontend_and_demo_assets_are_served():
    app = create_app(settings, FakeModels(), FakeService())
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/style.css").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/static/assets/demo-car.jpg").status_code == 200
        assert client.get("/static/assets/demo-showroom.jpg").status_code == 200
        assert client.get("/assets/demo-car.jpg").status_code == 200
