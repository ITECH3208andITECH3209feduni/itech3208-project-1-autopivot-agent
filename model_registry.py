"""AutoPivot model registry. Loads AI models lazily, reuses them, and handles configured fallbacks."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from config import Settings, settings
from errors import ModelError

logger = logging.getLogger("autopivot.models")
SegmentationRunner = Callable[[Any, Image.Image], Image.Image]


class ModelRegistry:
    def __init__(self, config: Settings) -> None:
        self.config = config
        self.device = self._choose_device(config.device)
        self._token = ""
        self._authenticated = False

        self._rmbg: Any = None
        self._birefnet: Any = None
        self._vehicle: Any = None
        self._plates: Any = None

        self._rmbg_ok = False
        self._birefnet_ok = False
        self._vehicle_ok = False
        self._plates_ok = False

        self.active_yolo = "none"
        self.active_yolo_role = "none"

        self._auth_lock = threading.RLock()
        self._rmbg_lock = threading.RLock()
        self._birefnet_lock = threading.RLock()
        self._vehicle_lock = threading.RLock()
        self._plates_lock = threading.RLock()

    @staticmethod
    def _choose_device(selected: str) -> str:
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False

        if selected == "auto":
            return "cuda" if has_cuda else "cpu"
        if selected == "cuda" and not has_cuda:
            logger.warning("CUDA is unavailable. Using CPU.")
            return "cpu"
        return selected

    def startup(self) -> None:
        self.authenticate()
        if self.config.preload_background_models:
            self.load_background_models()

    def authenticate(self) -> None:
        if self._authenticated:
            return
        with self._auth_lock:
            if self._authenticated:
                return
            from huggingface_hub import get_token, login

            self._token = self.config.hf_token or (get_token() or "")
            self._authenticated = True
            if self.config.hf_token:
                try:
                    login(token=self.config.hf_token)
                except Exception as exc:
                    logger.warning("Hugging Face login failed: %s", exc)

    def load_background_models(self) -> None:
        self.authenticate()
        self._load_rmbg()
        if not self._rmbg_ok:
            self._load_birefnet()

    def _load_rmbg(self) -> None:
        if self._rmbg_ok:
            return
        with self._rmbg_lock:
            if self._rmbg_ok:
                return
            try:
                import torch
                from transformers import AutoModelForImageSegmentation

                self._rmbg = (
                    AutoModelForImageSegmentation.from_pretrained(
                        self.config.rmbg_model_id,
                        trust_remote_code=True,
                        torch_dtype=torch.float32,
                        token=self._token or None,
                    )
                    .eval()
                    .to(self.device)
                )
                self._rmbg_ok = True
            except Exception as exc:
                self._rmbg = None
                self._rmbg_ok = False
                logger.warning("Primary background model failed: %s", exc)

    def _load_birefnet(self) -> None:
        if self._birefnet_ok:
            return
        with self._birefnet_lock:
            if self._birefnet_ok:
                return
            try:
                import torch
                from transformers import AutoModelForImageSegmentation

                self._birefnet = (
                    AutoModelForImageSegmentation.from_pretrained(
                        self.config.birefnet_model_id,
                        trust_remote_code=True,
                        torch_dtype=torch.float32,
                        token=self._token or None,
                    )
                    .eval()
                    .to(self.device)
                )
                self._birefnet_ok = True
            except Exception as exc:
                self._birefnet = None
                self._birefnet_ok = False
                raise ModelError("background-removal fallback") from exc

    def active_background_model(self) -> tuple[Any, str]:
        if not self._rmbg_ok and not self._birefnet_ok:
            self.load_background_models()
        if self._rmbg_ok:
            return self._rmbg, self.config.rmbg_model_id
        if self._birefnet_ok:
            return self._birefnet, self.config.birefnet_model_id
        raise ModelError("background-removal")

    def remove_background(
        self,
        image: Image.Image,
        run_model: SegmentationRunner,
    ) -> tuple[Image.Image, str]:
        model, name = self.active_background_model()
        try:
            return run_model(model, image), name
        except Exception as primary_error:
            if name != self.config.rmbg_model_id:
                raise ModelError("background-removal") from primary_error
            logger.warning("RMBG-2.0 failed during processing. Using BiRefNet.")
            self._rmbg_ok = False
            self._load_birefnet()
            try:
                return run_model(self._birefnet, image), self.config.birefnet_model_id
            except Exception as fallback_error:
                raise ModelError("background-removal") from fallback_error

    def _primary_yolo_path(self) -> str:
        local_path = Path(self.config.yolo_primary_model_path).expanduser()
        if local_path.exists():
            return str(local_path)
        if self.config.yolo_primary_hf_repo:
            from huggingface_hub import hf_hub_download

            return hf_hub_download(
                repo_id=self.config.yolo_primary_hf_repo,
                filename=self.config.yolo_primary_model_path,
                token=self._token or None,
            )
        return self.config.yolo_primary_model_path

    def _load_vehicle_primary(self) -> None:
        from ultralytics import YOLO

        path = self._primary_yolo_path()
        self._vehicle = YOLO(path)
        self._vehicle_ok = True
        self.active_yolo = str(path)
        self.active_yolo_role = "primary"

    def _load_vehicle_fallback(self) -> None:
        if not self.config.enable_yolo_fallback:
            raise ModelError("vehicle detection")
        from ultralytics import YOLO

        path = self.config.yolo_fallback_model_path
        self._vehicle = YOLO(path)
        self._vehicle_ok = True
        self.active_yolo = str(path)
        self.active_yolo_role = "fallback"

    def _load_vehicle(self) -> None:
        if self._vehicle_ok:
            return
        with self._vehicle_lock:
            if self._vehicle_ok:
                return
            try:
                self._load_vehicle_primary()
            except Exception as primary_error:
                logger.warning("Primary YOLO model failed: %s", primary_error)
                try:
                    self._load_vehicle_fallback()
                except Exception as fallback_error:
                    raise ModelError("vehicle detection") from fallback_error

    @staticmethod
    def _largest_vehicle(results: Any, allowed_classes: frozenset[str]) -> dict[str, Any] | None:
        vehicles: list[dict[str, Any]] = []
        for result in results:
            for box in result.boxes:
                name = result.names[int(box.cls[0])]
                if name not in allowed_classes:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                vehicles.append(
                    {
                        "class": name,
                        "score": float(box.conf[0]),
                        "box": {
                            "xmin": int(x1),
                            "ymin": int(y1),
                            "xmax": int(x2),
                            "ymax": int(y2),
                        },
                        "area": max(0.0, x2 - x1) * max(0.0, y2 - y1),
                    }
                )
        return max(vehicles, key=lambda item: item["area"]) if vehicles else None

    def detect_vehicle(self, image: Image.Image, confidence: float) -> dict[str, Any] | None:
        self._load_vehicle()
        try:
            results = self._vehicle(image, conf=confidence, verbose=False)
        except Exception as primary_error:
            if self.active_yolo_role != "primary" or not self.config.enable_yolo_fallback:
                raise ModelError("vehicle detection") from primary_error
            logger.warning("YOLO26 failed during processing. Using YOLO11.")
            with self._vehicle_lock:
                self._load_vehicle_fallback()
            try:
                results = self._vehicle(image, conf=confidence, verbose=False)
            except Exception as fallback_error:
                raise ModelError("vehicle detection") from fallback_error
        return self._largest_vehicle(results, self.config.vehicle_classes)

    def _load_plates(self) -> None:
        if self._plates_ok:
            return
        with self._plates_lock:
            if self._plates_ok:
                return
            try:
                from transformers import pipeline

                self._plates = pipeline(
                    "object-detection",
                    model=self.config.plate_model_id,
                    token=self._token or None,
                )
                self._plates_ok = True
            except Exception as exc:
                raise ModelError("licence-plate detection") from exc

    def detect_plates(self, image: Image.Image, confidence: float) -> list[dict[str, Any]]:
        self._load_plates()
        try:
            detections = self._plates(image.convert("RGB"))
        except Exception as exc:
            raise ModelError("licence-plate detection") from exc
        return [item for item in detections if float(item["score"]) > confidence]

    def health(self) -> dict[str, Any]:
        if self._rmbg_ok:
            active_bg = self.config.rmbg_model_id
        elif self._birefnet_ok:
            active_bg = f"{self.config.birefnet_model_id} (fallback)"
        else:
            active_bg = "none"
        return {
            "device": self.device,
            "active_bg_model": active_bg,
            "rmbg_loaded": self._rmbg_ok,
            "birefnet_loaded": self._birefnet_ok,
            "active_yolo_model": self.active_yolo,
            "active_yolo_role": self.active_yolo_role,
            "vehicle_detector_loaded": self._vehicle_ok,
            "plate_detector_loaded": self._plates_ok,
        }


registry = ModelRegistry(settings)
