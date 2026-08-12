"""AutoPivot image-processing pipeline.

What this file does: detects a vehicle, removes its background, places it into a
selected showroom, applies light edge/colour/shadow matching, and hides number
plates. The display-base logic uses one ellipse and one contact line instead of
separate measurement and rim-mask systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from config import BackgroundPreset, Settings, settings
from errors import AppError, NoPlateError, NoVehicleError
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
        background_style: str | None = None,
    ) -> PipelineResult:
        source = image.convert("RGB")
        vehicle = self.models.detect_vehicle(source, self.config.vehicle_confidence)
        if vehicle is None:
            raise NoVehicleError()

        crop, _ = self._crop_vehicle(source, vehicle["box"])
        cutout, model_used = self.models.remove_background(crop, self._segment)
        cutout = self._trim_transparent(cutout)

        background_image, preset = self._resolve_background(background, background_style)
        result, vehicle_layer, composite_meta = self._composite(cutout, background_image, preset)

        plates = self.models.detect_plates(vehicle_layer, self.config.plate_confidence)
        result = self._hide_plates(result, plates, plate_overlay)

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
                "background_removed": True,
                "detections": self._clean_detections(plates),
                **composite_meta,
            },
        )

    def remove_background(
        self,
        image: Image.Image,
        background: Image.Image | None = None,
        background_style: str | None = None,
    ) -> PipelineResult:
        cutout, model_used = self.models.remove_background(image, self._segment)
        cutout = self._trim_transparent(cutout)
        background_image, preset = self._resolve_background(background, background_style)
        result, _, composite_meta = self._composite(cutout, background_image, preset)
        return PipelineResult(
            result,
            {
                "bg_model_used": model_used,
                "background_removed": True,
                **composite_meta,
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
        return PipelineResult(
            self._hide_plates(source, plates, plate_overlay),
            {
                "plates_detected": len(plates),
                "plate_treatment": "overlay" if plate_overlay else "blanked",
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
            mask = transforms.ToPILImage()(prediction.sigmoid().cpu()[0].squeeze())

        alpha = self._refine_alpha_mask(mask.resize(source.size, Image.Resampling.LANCZOS))
        result = source.convert("RGBA")
        result.putalpha(alpha)
        return result

    @staticmethod
    def _refine_alpha_mask(mask: Image.Image) -> Image.Image:
        """Small edge cleanup to reduce holes and white fringes without over-processing."""
        alpha = np.array(mask.convert("L"), dtype=np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
        alpha = cv2.erode(alpha, kernel, iterations=1)
        alpha = cv2.GaussianBlur(alpha, (0, 0), 0.65)
        alpha[alpha <= 2] = 0
        alpha[alpha >= 253] = 255
        return Image.fromarray(alpha, mode="L")

    def _crop_vehicle(
        self, image: Image.Image, box: dict[str, int]
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        width, height = image.size
        x1, y1, x2, y2 = box["xmin"], box["ymin"], box["xmax"], box["ymax"]
        pad_x = int((x2 - x1) * self.config.crop_padding_ratio)
        pad_y = int((y2 - y1) * self.config.crop_padding_ratio)
        region = (
            max(0, x1 - pad_x),
            max(0, y1 - pad_y),
            min(width, x2 + pad_x),
            min(height, y2 + pad_y),
        )
        return image.crop(region), region

    @staticmethod
    def _trim_transparent(cutout: Image.Image) -> Image.Image:
        cutout = cutout.convert("RGBA")
        alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
        bbox = Image.fromarray((alpha > 4).astype(np.uint8) * 255, mode="L").getbbox()
        if bbox is None:
            return cutout
        left, top, right, bottom = bbox
        return cutout.crop(
            (max(0, left - 2), max(0, top - 2), min(cutout.width, right + 2), min(cutout.height, bottom + 2))
        )

    def _resolve_background(
        self,
        uploaded: Image.Image | None,
        background_style: str | None,
    ) -> tuple[Image.Image | None, BackgroundPreset | None]:
        if uploaded is not None:
            preset = BackgroundPreset(
                key="custom",
                label="Custom Background",
                filename="",
                placement="ground",
                surface="floor",
                ground_y_ratio=0.84,
            )
            return uploaded.convert("RGBA"), preset

        style = background_style or self.config.default_background_style
        style = {
            "studio": "studio_full",
            "full": "studio_full",
            "closeup": "studio_closeup",
            "interior": "studio_closeup",
        }.get(style, style)

        if style in {"transparent", "none"}:
            return None, None
        if style == "custom":
            raise AppError(
                "BACKGROUND_REQUIRED",
                "Custom Background was selected but no background image was uploaded.",
                400,
            )

        preset = self.config.background_preset(style)
        if preset is None:
            raise AppError("INVALID_BACKGROUND_STYLE", f"Unknown background style: {style}", 400)

        path = self.config.background_dir / preset.filename
        if not path.exists():
            raise AppError(
                "BACKGROUND_NOT_FOUND",
                f"The showroom background '{preset.filename}' is missing from assets/backgrounds.",
                500,
            )
        try:
            return Image.open(path).convert("RGBA"), preset
        except OSError as exc:
            raise AppError(
                "BACKGROUND_INVALID",
                f"The showroom background '{preset.filename}' could not be opened.",
                500,
            ) from exc

    def _composite(
        self,
        cutout: Image.Image,
        background: Image.Image | None,
        preset: BackgroundPreset | None,
    ) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
        size = (self.config.output_width, self.config.output_height)
        background_canvas = (
            self._fit_background(background, size)
            if background is not None
            else Image.new("RGBA", size, (0, 0, 0, 0))
        )

        vehicle = self._fit_vehicle(cutout, preset)
        x, y, ground_y = self._vehicle_position(vehicle, preset)

        colour_matched = background is not None
        if colour_matched:
            vehicle = self._match_colour(vehicle, background_canvas, x, y)

        vehicle_layer = Image.new("RGBA", size, (0, 0, 0, 0))
        vehicle_layer.paste(vehicle, (x, y), vehicle.getchannel("A"))

        if background is None:
            result = vehicle_layer
            shadow_applied = False
        else:
            result = background_canvas.copy()
            shadow_applied = bool(preset and preset.placement == "ground")
            if shadow_applied:
                clip_mask = self._platform_mask(preset) if preset and preset.platform_box else None
                for shadow, position in self._shadows(vehicle.getchannel("A"), x, ground_y):
                    self._composite_clipped(result, shadow, position, clip_mask)
            result.alpha_composite(vehicle_layer)

        return result, vehicle_layer, {
            "background": preset.label if preset else "Transparent",
            "background_style": preset.key if preset else "transparent",
            "output_size": {"width": size[0], "height": size[1]},
            "ground_aligned": bool(preset and preset.placement == "ground"),
            "shadow_applied": shadow_applied,
            "colour_matched": colour_matched,
            "transparency_preserved": background is None,
        }

    @staticmethod
    def _fit_background(background: Image.Image, size: tuple[int, int]) -> Image.Image:
        target_w, target_h = size
        source = background.convert("RGBA")
        scale = max(target_w / source.width, target_h / source.height)
        resized = source.resize(
            (round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS
        )
        left = max(0, (resized.width - target_w) // 2)
        top = max(0, (resized.height - target_h) // 2)
        return resized.crop((left, top, left + target_w, top + target_h))

    def _fit_vehicle(self, cutout: Image.Image, preset: BackgroundPreset | None) -> Image.Image:
        cutout = cutout.convert("RGBA")
        if preset and preset.platform_box:
            platform_width = self.config.output_width * (preset.platform_box[2] - preset.platform_box[0])
            max_width = platform_width * preset.vehicle_width_ratio
            max_height = self.config.output_height * preset.vehicle_height_ratio
        elif preset:
            max_width = self.config.output_width * preset.vehicle_width_ratio
            max_height = self.config.output_height * preset.vehicle_height_ratio
        else:
            max_width = self.config.output_width * 0.72
            max_height = self.config.output_height * 0.60

        scale = min(max_width / cutout.width, max_height / cutout.height)
        return cutout.resize(
            (max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))),
            Image.Resampling.LANCZOS,
        )

    def _vehicle_position(
        self, vehicle: Image.Image, preset: BackgroundPreset | None
    ) -> tuple[int, int, int]:
        canvas_w, canvas_h = self.config.output_width, self.config.output_height
        left, top, right, bottom = self._visible_bounds(vehicle)
        visible_center_x = (left + right) / 2

        if preset and preset.platform_box:
            platform_center_x = canvas_w * (preset.platform_box[0] + preset.platform_box[2]) / 2
            x = round(platform_center_x - visible_center_x)
        else:
            x = round(canvas_w / 2 - visible_center_x)

        if preset and preset.placement == "center":
            visible_center_y = (top + bottom) / 2
            y = round(canvas_h * 0.52 - visible_center_y)
            return int(x), int(y), min(canvas_h - 1, int(y + bottom))

        contact_y = self._contact_y(vehicle) if preset and preset.platform_box else bottom
        ground_ratio = (
            preset.platform_contact_y_ratio
            if preset and preset.platform_contact_y_ratio is not None
            else preset.ground_y_ratio if preset else 0.84
        )
        ground_y = round(canvas_h * ground_ratio)
        y = round(ground_y - contact_y)
        return int(x), int(y), int(ground_y)

    @staticmethod
    def _visible_bounds(image: Image.Image) -> tuple[int, int, int, int]:
        alpha = np.array(image.getchannel("A"), dtype=np.uint8)
        ys, xs = np.where(alpha > 6)
        if xs.size == 0 or ys.size == 0:
            return 0, 0, image.width, image.height
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

    @staticmethod
    def _contact_y(vehicle: Image.Image) -> int:
        """Use a robust lower silhouette line so faint mask remnants do not lift the car."""
        mask = np.array(vehicle.getchannel("A"), dtype=np.uint8) >= 96
        bottoms = [int(ys[-1]) for x in range(mask.shape[1]) if (ys := np.flatnonzero(mask[:, x])).size]
        if not bottoms:
            return VehiclePipelineService._visible_bounds(vehicle)[3]
        return int(round(float(np.quantile(np.asarray(bottoms, dtype=np.float32), 0.97))))

    def _platform_mask(self, preset: BackgroundPreset) -> Image.Image | None:
        if not preset.platform_box:
            return None
        x1, y1, x2, y2 = preset.platform_box
        box = (
            round(self.config.output_width * x1),
            round(self.config.output_height * y1),
            round(self.config.output_width * x2),
            round(self.config.output_height * y2),
        )
        mask = Image.new("L", (self.config.output_width, self.config.output_height), 0)
        ImageDraw.Draw(mask).ellipse(box, fill=255)
        return mask

    def _shadows(
        self, alpha: Image.Image, vehicle_x: int, ground_y: int
    ) -> list[tuple[Image.Image, tuple[int, int]]]:
        return [
            self._build_shadow(alpha, vehicle_x, ground_y, 0.14, 24, 0.14, 1.04),
            self._build_shadow(alpha, vehicle_x, ground_y, 0.32, 12, 0.075, 0.90),
        ]

    def _build_shadow(
        self,
        alpha: Image.Image,
        vehicle_x: int,
        ground_y: int,
        opacity: float,
        blur: float,
        height_ratio: float,
        width_scale: float,
    ) -> tuple[Image.Image, tuple[int, int]]:
        source = alpha.convert("L")
        width = max(1, round(source.width * width_scale))
        height = max(4, round(source.height * height_ratio))
        compressed = source.resize((width, height), Image.Resampling.LANCZOS)
        padding = max(2, round(blur * 2))

        mask = Image.new("L", (width + padding * 2, height + padding * 2), 0)
        mask.paste(compressed, (padding, padding))
        mask = mask.point(lambda value: int(value * opacity)).filter(ImageFilter.GaussianBlur(blur))

        shadow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        shadow.putalpha(mask)
        x = vehicle_x + (source.width - width) // 2 - padding
        y = ground_y - height // 2 - padding - 2
        return shadow, (x, y)

    @staticmethod
    def _composite_clipped(
        result: Image.Image,
        layer: Image.Image,
        position: tuple[int, int],
        clip_mask: Image.Image | None,
    ) -> None:
        if clip_mask is None:
            result.alpha_composite(layer, position)
            return

        full = Image.new("RGBA", result.size, (0, 0, 0, 0))
        full.alpha_composite(layer, position)
        full_alpha = np.array(full.getchannel("A"), dtype=np.float32)
        clip = np.array(clip_mask, dtype=np.float32) / 255.0
        full.putalpha(Image.fromarray(np.clip(full_alpha * clip, 0, 255).astype(np.uint8), mode="L"))
        result.alpha_composite(full)

    @staticmethod
    def _background_patch(
        background: Image.Image, x: int, y: int, width: int, height: int
    ) -> np.ndarray:
        margin_x, margin_y = max(8, width // 10), max(8, height // 10)
        box = (
            max(0, x - margin_x),
            max(0, y - margin_y),
            min(background.width, x + width + margin_x),
            min(background.height, y + height + margin_y),
        )
        return np.array(background.crop(box).convert("RGB"), dtype=np.uint8)

    def _match_colour(
        self, vehicle: Image.Image, background: Image.Image, x: int, y: int
    ) -> Image.Image:
        """Apply a weak LAB mean shift so the cutout better matches the showroom light."""
        rgba = np.array(vehicle.convert("RGBA"), dtype=np.uint8)
        opaque = rgba[:, :, 3] > 24
        patch = self._background_patch(background, x, y, vehicle.width, vehicle.height)
        if not np.any(opaque) or patch.size == 0:
            return vehicle

        vehicle_lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
        background_lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
        vehicle_mean = vehicle_lab[opaque].mean(axis=0)
        background_mean = background_lab.reshape(-1, 3).mean(axis=0)

        vehicle_lab[:, :, 0] += np.clip((background_mean[0] - vehicle_mean[0]) * 0.12, -18, 18)
        vehicle_lab[:, :, 1:3] += np.clip(
            (background_mean[1:3] - vehicle_mean[1:3]) * 0.15, -5, 5
        )

        rgba[:, :, :3] = cv2.cvtColor(
            np.clip(vehicle_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB
        )
        return Image.fromarray(rgba, mode="RGBA")

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

        return Image.fromarray(output, mode="RGBA")

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
