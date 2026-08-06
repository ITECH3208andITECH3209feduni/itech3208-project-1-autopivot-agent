from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image

from config import Settings, settings
from errors import NoPlateError, NoVehicleError
from model_registry import ModelRegistry, registry


@dataclass
class PipelineResult:
    image: Image.Image
    metadata: dict[str, Any] = field(default_factory=dict)


class VehiclePipelineService:
    def __init__(self, models: ModelRegistry, config: Settings) -> None:
        self.models = models
        self.config = config

    def process_vehicle(
        self,
        image: Image.Image,
        background: Image.Image | None = None,
        plate_overlay: Image.Image | None = None,
    ) -> PipelineResult:
        source = image.convert("RGB")
        vehicle = self.models.detect_vehicle(source, self.config.vehicle_confidence)
        if vehicle is None:
            raise NoVehicleError()

        crop, position = self._crop_vehicle(source, vehicle["box"])
        cutout, model_used = self.models.remove_background(crop, self._segment)
        result = self._place_on_canvas(source, cutout, position)
        plates = self.models.detect_plates(result, self.config.plate_confidence)
        result = self._hide_plates(result, plates, plate_overlay)
        result = self._add_background(result, background)

        return PipelineResult(
            result,
            {
                "vehicle_detected": True,
                "vehicle": {
                    "class": vehicle["class"],
                    "score": round(float(vehicle["score"]), 4),
                    "box": vehicle["box"],
                },
                "bg_model_used": model_used,
                "plates_detected": len(plates),
                "plate_treatment": "overlay" if plate_overlay else "blanked",
                "background_applied": "custom" if background else "transparent",
                "background_removed": True,
                "transparency_preserved": background is None,
                "detections": self._clean_detections(plates),
            },
        )

    def remove_background(
        self,
        image: Image.Image,
        background: Image.Image | None = None,
    ) -> PipelineResult:
        cutout, model_used = self.models.remove_background(image, self._segment)
        result = self._add_background(cutout, background)
        return PipelineResult(
            result,
            {
                "bg_model_used": model_used,
                "background_removed": True,
                "background_applied": "custom" if background else "transparent",
                "transparency_preserved": background is None,
            },
        )

    def detect_and_hide(
        self,
        image: Image.Image,
        plate_overlay: Image.Image | None = None,
    ) -> PipelineResult:
        source = image.convert("RGBA")
        plates = self.models.detect_plates(source, self.config.plate_confidence)
        if not plates:
            raise NoPlateError()
        result = self._hide_plates(source, plates, plate_overlay)
        return PipelineResult(
            result,
            {
                "plates_detected": len(plates),
                "plate_treatment": "overlay" if plate_overlay else "blanked",
                "transparency_preserved": True,
                "detections": self._clean_detections(plates),
            },
        )

    def _segment(self, model: Any, image: Image.Image) -> Image.Image:
        import torch
        from torchvision import transforms

        transform = transforms.Compose(
            [
                transforms.Resize((self.config.segmentation_size, self.config.segmentation_size)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        source = image.convert("RGB")
        tensor = transform(source).unsqueeze(0).to(self.models.device)
        with torch.no_grad():
            output = model(tensor)
            prediction = output[-1] if isinstance(output, (list, tuple)) else output
            mask_tensor = prediction.sigmoid().cpu()[0].squeeze()
        mask = transforms.ToPILImage()(mask_tensor).resize(source.size, Image.Resampling.LANCZOS)
        result = source.convert("RGBA")
        result.putalpha(mask)
        return result

    def _crop_vehicle(
        self,
        image: Image.Image,
        box: dict[str, int],
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        width, height = image.size
        x1, y1, x2, y2 = box["xmin"], box["ymin"], box["xmax"], box["ymax"]
        pad_x = int((x2 - x1) * self.config.crop_padding_ratio)
        pad_y = int((y2 - y1) * self.config.crop_padding_ratio)
        position = (
            max(0, x1 - pad_x),
            max(0, y1 - pad_y),
            min(width, x2 + pad_x),
            min(height, y2 + pad_y),
        )
        return image.crop(position), position

    @staticmethod
    def _place_on_canvas(
        original: Image.Image,
        cutout: Image.Image,
        position: tuple[int, int, int, int],
    ) -> Image.Image:
        x1, y1, x2, y2 = position
        canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
        cutout = cutout.convert("RGBA").resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
        canvas.paste(cutout, (x1, y1), cutout.getchannel("A"))
        return canvas

    def _hide_plates(
        self,
        image: Image.Image,
        plates: list[dict[str, Any]],
        overlay: Image.Image | None,
    ) -> Image.Image:
        output = np.array(image.convert("RGBA"), dtype=np.uint8)
        padding = self.config.plate_box_padding

        for plate in plates:
            box = plate["box"]
            x1 = max(0, int(box["xmin"]) - padding)
            y1 = max(0, int(box["ymin"]) - padding)
            x2 = min(output.shape[1], int(box["xmax"]) + padding)
            y2 = min(output.shape[0], int(box["ymax"]) + padding)
            if x2 <= x1 or y2 <= y1:
                continue

            if overlay is None:
                cv2.rectangle(output, (x1, y1), (x2 - 1, y2 - 1), (255, 255, 255, 255), -1)
                continue

            plate_image = overlay.convert("RGBA").resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
            plate_array = np.array(plate_image, dtype=np.float32)
            alpha = plate_array[:, :, 3:4] / 255.0
            base = output[y1:y2, x1:x2].astype(np.float32)
            output[y1:y2, x1:x2, :3] = (
                plate_array[:, :, :3] * alpha + base[:, :, :3] * (1 - alpha)
            ).clip(0, 255).astype(np.uint8)
            output[y1:y2, x1:x2, 3] = np.maximum(base[:, :, 3], plate_array[:, :, 3]).astype(np.uint8)

        return Image.fromarray(output, "RGBA")

    @staticmethod
    def _add_background(foreground: Image.Image, background: Image.Image | None) -> Image.Image:
        foreground = foreground.convert("RGBA")
        if background is None:
            return foreground
        background = background.convert("RGBA").resize(foreground.size, Image.Resampling.LANCZOS)
        return Image.alpha_composite(background, foreground)

    @staticmethod
    def _clean_detections(plates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "score": round(float(plate["score"]), 4),
                "box": {key: int(value) for key, value in plate["box"].items()},
            }
            for plate in plates
        ]


pipeline = VehiclePipelineService(registry, settings)
