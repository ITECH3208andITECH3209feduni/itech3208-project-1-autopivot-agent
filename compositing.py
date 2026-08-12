"""Placing a cut-out vehicle into a scene so it reads as photographed in it.

The compositing here is Suraj Purella's, from the Auto_pivot_Scaling branch
(`pipeline_service.py`). His branch replaced the whole application with a
standalone processing service, so rather than merging it the compositing was
lifted out and the platform left alone. The geometry, the shadow construction
and the LAB matching are his; the packaging and the dealer-backdrop path are
the adaptation.

A straight paste fails for three reasons, and this addresses each:

  * The mask is computed at 1024x1024 and stretched over a 3000-pixel
    photograph, which leaves soft, haloed edges. `refine_alpha_mask` closes
    pinholes, pulls the edge in a pixel and feathers it.
  * Nothing anchors the vehicle to the floor, so it floats. `build_shadow`
    lays down an ambient pool and a tighter contact shadow, derived from the
    vehicle's own silhouette rather than a generic ellipse.
  * The photograph and the backdrop were lit differently. `match_colour`
    nudges the vehicle towards the backdrop's LAB mean, weakly and clamped —
    strongly enough to sit, not so strongly that the paint changes colour,
    which would matter on a listing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("autopivot.compositing")

BACKGROUND_DIR = Path(__file__).resolve().parent / "assets" / "backgrounds"

# A dealer backdrop can be any size; this bounds the working canvas so a large
# upload cannot turn one job into a memory problem.
MAX_CANVAS_WIDTH = 2400


@dataclass(frozen=True)
class BackdropPreset:
    """
    How a vehicle sits in a particular scene.

    All geometry is expressed as a ratio of the canvas, so one preset holds
    whatever size the scene is rendered at.
    """

    key: str
    label: str
    filename: str = ""
    # "ground" stands the vehicle on a surface; "center" places it in frame
    # without a contact point, for close-ups shot against a wall.
    placement: str = "ground"
    ground_y_ratio: float = 0.84
    # x1, y1, x2, y2 of the display base, as canvas ratios. Present only for
    # scenes measured by hand — it clips shadows to the platform surface.
    platform_box: tuple[float, float, float, float] | None = None
    platform_contact_y_ratio: float | None = None
    vehicle_width_ratio: float = 0.72
    vehicle_height_ratio: float = 0.60
    # None means "use the backdrop's own dimensions", which is what a dealer
    # upload wants — their scene, their resolution.
    output_size: tuple[int, int] | None = None


# Measured by Suraj Purella against the rendered showroom. The reference was
# 1448x1086 and the output is 1280x960; both are 4:3, so the ratios carry over
# without distortion.
STUDIO_FULL = BackdropPreset(
    key="studio_full",
    label="AutoPivot Studio — Full Car",
    filename="studio-full.png",
    placement="ground",
    ground_y_ratio=0.755,
    platform_box=(0.105, 0.598, 0.875, 0.820),
    platform_contact_y_ratio=0.755,
    vehicle_width_ratio=0.86,
    vehicle_height_ratio=0.54,
    output_size=(1280, 960),
)

STUDIO_CLOSEUP = BackdropPreset(
    key="studio_closeup",
    label="AutoPivot Studio — Close-up",
    filename="studio-closeup.png",
    placement="center",
    ground_y_ratio=0.82,
    vehicle_width_ratio=0.86,
    vehicle_height_ratio=0.78,
    output_size=(1280, 960),
)

STUDIO_PRESETS: dict[str, BackdropPreset] = {
    STUDIO_FULL.key: STUDIO_FULL,
    STUDIO_CLOSEUP.key: STUDIO_CLOSEUP,
}

# What a dealership's own backdrop gets. No measured platform, so shadows are
# not clipped and the vehicle stands on a nominal ground line.
DEALER_BACKDROP = BackdropPreset(key="custom", label="Dealership backdrop")


def load_studio_backdrop(key: str) -> tuple[Image.Image, BackdropPreset] | None:
    """Open a built-in scene, or None if the key is unknown or the file is absent."""
    preset = STUDIO_PRESETS.get(key)
    if preset is None:
        return None
    path = BACKGROUND_DIR / preset.filename
    if not path.exists():
        logger.warning("Studio backdrop '%s' is missing from %s", preset.filename, BACKGROUND_DIR)
        return None
    try:
        return Image.open(path).convert("RGBA"), preset
    except OSError as exc:
        logger.warning("Studio backdrop '%s' could not be opened: %s", preset.filename, exc)
        return None


# ── Mask cleanup ───────────────────────────────────────────────────────────────

def refine_alpha_mask(mask: Image.Image) -> Image.Image:
    """
    Tidy a segmentation mask: close pinholes, pull the edge in, feather it.

    The erode is what removes the light fringe of background that the model
    leaves around the silhouette — visible as a halo once the vehicle sits on a
    darker scene. Kept to one pixel: more starts eating wing mirrors and aerials.
    """
    alpha = np.array(mask.convert("L"), dtype=np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    alpha = cv2.erode(alpha, kernel, iterations=1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.65)
    # Snap the near-extremes so the cutout has genuinely clear and genuinely
    # solid regions rather than a wash of almost-zero alpha.
    alpha[alpha <= 2] = 0
    alpha[alpha >= 253] = 255
    return Image.fromarray(alpha, mode="L")


def trim_transparent(cutout: Image.Image) -> Image.Image:
    """Crop to the visible vehicle, keeping a 2px margin."""
    cutout = cutout.convert("RGBA")
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    bbox = Image.fromarray((alpha > 4).astype(np.uint8) * 255, mode="L").getbbox()
    if bbox is None:
        return cutout
    left, top, right, bottom = bbox
    return cutout.crop((
        max(0, left - 2),
        max(0, top - 2),
        min(cutout.width, right + 2),
        min(cutout.height, bottom + 2),
    ))


# ── Geometry ───────────────────────────────────────────────────────────────────

def _visible_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha > 6)
    if xs.size == 0 or ys.size == 0:
        return 0, 0, image.width, image.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _contact_y(vehicle: Image.Image) -> int:
    """
    The line the tyres sit on.

    Deliberately not the lowest opaque pixel: a single stray row of mask —
    a shadow remnant from the original ground, a segmentation spike — would
    lift the whole car off the floor. Taking the 0.97 quantile of each column's
    lowest solid pixel ignores those without losing the real contact line.
    """
    mask = np.array(vehicle.getchannel("A"), dtype=np.uint8) >= 96
    bottoms = [
        int(ys[-1])
        for x in range(mask.shape[1])
        if (ys := np.flatnonzero(mask[:, x])).size
    ]
    if not bottoms:
        return _visible_bounds(vehicle)[3]
    return int(round(float(np.quantile(np.asarray(bottoms, dtype=np.float32), 0.97))))


def _canvas_size(backdrop: Image.Image, preset: BackdropPreset) -> tuple[int, int]:
    if preset.output_size is not None:
        return preset.output_size
    width, height = backdrop.size
    if width > MAX_CANVAS_WIDTH:
        height = max(1, round(height * MAX_CANVAS_WIDTH / width))
        width = MAX_CANVAS_WIDTH
    return width, height


def _fit_backdrop(backdrop: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cover the canvas without distorting: scale to fill, then centre-crop."""
    target_w, target_h = size
    source = backdrop.convert("RGBA")
    scale = max(target_w / source.width, target_h / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _fit_vehicle(
    cutout: Image.Image, preset: BackdropPreset, size: tuple[int, int]
) -> Image.Image:
    canvas_w, canvas_h = size
    if preset.platform_box:
        # Scale against the display base rather than the whole frame, so the
        # car sits on the platform instead of overhanging it.
        platform_width = canvas_w * (preset.platform_box[2] - preset.platform_box[0])
        max_width = platform_width * preset.vehicle_width_ratio
    else:
        max_width = canvas_w * preset.vehicle_width_ratio
    max_height = canvas_h * preset.vehicle_height_ratio

    scale = min(max_width / cutout.width, max_height / cutout.height)
    return cutout.resize(
        (max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))),
        Image.Resampling.LANCZOS,
    )


def _vehicle_position(
    vehicle: Image.Image, preset: BackdropPreset, size: tuple[int, int]
) -> tuple[int, int, int]:
    """Return where to paste the vehicle, and the y of the ground line."""
    canvas_w, canvas_h = size
    left, top, right, bottom = _visible_bounds(vehicle)

    if preset.platform_box:
        platform_centre_x = canvas_w * (preset.platform_box[0] + preset.platform_box[2]) / 2
        x = round(platform_centre_x - (left + right) / 2)
    else:
        x = round(canvas_w / 2 - (left + right) / 2)

    if preset.placement == "center":
        y = round(canvas_h * 0.52 - (top + bottom) / 2)
        return int(x), int(y), min(canvas_h - 1, int(y + bottom))

    contact = _contact_y(vehicle) if preset.platform_box else bottom
    ratio = (
        preset.platform_contact_y_ratio
        if preset.platform_contact_y_ratio is not None
        else preset.ground_y_ratio
    )
    ground_y = round(canvas_h * ratio)
    return int(x), int(round(ground_y - contact)), int(ground_y)


def _platform_mask(preset: BackdropPreset, size: tuple[int, int]) -> Image.Image | None:
    """An ellipse over the display base, so shadows cannot spill off its edge."""
    if not preset.platform_box:
        return None
    canvas_w, canvas_h = size
    x1, y1, x2, y2 = preset.platform_box
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(
        (
            round(canvas_w * x1), round(canvas_h * y1),
            round(canvas_w * x2), round(canvas_h * y2),
        ),
        fill=255,
    )
    return mask


# ── Shadows ────────────────────────────────────────────────────────────────────

def _build_shadow(
    alpha: Image.Image,
    vehicle_x: int,
    ground_y: int,
    opacity: float,
    blur: float,
    height_ratio: float,
    width_scale: float,
) -> tuple[Image.Image, tuple[int, int]]:
    """
    Squash the vehicle's own silhouette into a shadow on the floor.

    Using the silhouette rather than an ellipse is what makes it read: the
    shadow narrows at the bonnet and widens at the wheel arches the way the
    car does.
    """
    source = alpha.convert("L")
    width = max(1, round(source.width * width_scale))
    height = max(4, round(source.height * height_ratio))
    compressed = source.resize((width, height), Image.Resampling.LANCZOS)

    # Pad before blurring so the falloff is not clipped at the edges.
    padding = max(2, round(blur * 2))
    mask = Image.new("L", (width + padding * 2, height + padding * 2), 0)
    mask.paste(compressed, (padding, padding))
    mask = mask.point(lambda v: int(v * opacity)).filter(ImageFilter.GaussianBlur(blur))

    shadow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    shadow.putalpha(mask)
    return shadow, (
        vehicle_x + (source.width - width) // 2 - padding,
        ground_y - height // 2 - padding - 2,
    )


def _shadows(
    alpha: Image.Image, vehicle_x: int, ground_y: int
) -> list[tuple[Image.Image, tuple[int, int]]]:
    """Ambient pool first, then the tighter darker contact shadow over it."""
    return [
        _build_shadow(alpha, vehicle_x, ground_y, 0.14, 24, 0.14, 1.04),
        _build_shadow(alpha, vehicle_x, ground_y, 0.32, 12, 0.075, 0.90),
    ]


def _alpha_composite_at(
    canvas: Image.Image, layer: Image.Image, position: tuple[int, int]
) -> None:
    """
    alpha_composite that tolerates a layer hanging off any edge.

    Shadows are wider than the vehicle and padded by twice the blur radius, so
    on a small backdrop the destination goes negative or runs past the right
    or bottom edge. Pillow's own handling of that is version-dependent, so the
    overhang is cropped here and the destination clamped.
    """
    x, y = position
    left, top = max(0, -x), max(0, -y)
    if left >= layer.width or top >= layer.height:
        return

    x, y = max(0, x), max(0, y)
    if x >= canvas.width or y >= canvas.height:
        return

    right = min(layer.width, left + canvas.width - x)
    bottom = min(layer.height, top + canvas.height - y)
    if right <= left or bottom <= top:
        return

    if (left, top, right, bottom) != (0, 0, layer.width, layer.height):
        layer = layer.crop((left, top, right, bottom))
    canvas.alpha_composite(layer, (x, y))


def _composite_clipped(
    canvas: Image.Image,
    layer: Image.Image,
    position: tuple[int, int],
    clip: Image.Image | None,
) -> None:
    if clip is None:
        _alpha_composite_at(canvas, layer, position)
        return

    staged = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _alpha_composite_at(staged, layer, position)
    staged_alpha = np.array(staged.getchannel("A"), dtype=np.float32)
    clip_alpha = np.array(clip, dtype=np.float32) / 255.0
    staged.putalpha(
        Image.fromarray(np.clip(staged_alpha * clip_alpha, 0, 255).astype(np.uint8), mode="L")
    )
    canvas.alpha_composite(staged)


# ── Colour ─────────────────────────────────────────────────────────────────────

def _backdrop_patch(backdrop: Image.Image, x: int, y: int, width: int, height: int) -> np.ndarray:
    """The region of the scene the vehicle will occupy, plus a margin."""
    margin_x, margin_y = max(8, width // 10), max(8, height // 10)
    return np.array(
        backdrop.crop((
            max(0, x - margin_x),
            max(0, y - margin_y),
            min(backdrop.width, x + width + margin_x),
            min(backdrop.height, y + height + margin_y),
        )).convert("RGB"),
        dtype=np.uint8,
    )


def match_colour(
    vehicle: Image.Image, backdrop: Image.Image, x: int, y: int
) -> Image.Image:
    """
    Nudge the vehicle towards the scene's lighting. Weak and clamped on purpose.

    Lightness moves at 12% of the difference and no more than 18 LAB units;
    the colour axes at 15% and no more than 5. A dealer's photograph has to
    stay the colour the car actually is, so this corrects for the light it was
    shot under and stops well short of repainting it.
    """
    rgba = np.array(vehicle.convert("RGBA"), dtype=np.uint8)
    opaque = rgba[:, :, 3] > 24
    patch = _backdrop_patch(backdrop, x, y, vehicle.width, vehicle.height)
    if not np.any(opaque) or patch.size == 0:
        return vehicle

    vehicle_lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    backdrop_lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    vehicle_mean = vehicle_lab[opaque].mean(axis=0)
    backdrop_mean = backdrop_lab.reshape(-1, 3).mean(axis=0)

    vehicle_lab[:, :, 0] += np.clip((backdrop_mean[0] - vehicle_mean[0]) * 0.12, -18, 18)
    vehicle_lab[:, :, 1:3] += np.clip((backdrop_mean[1:3] - vehicle_mean[1:3]) * 0.15, -5, 5)

    rgba[:, :, :3] = cv2.cvtColor(
        np.clip(vehicle_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB
    )
    return Image.fromarray(rgba, mode="RGBA")


# ── Entry point ────────────────────────────────────────────────────────────────

def compose(
    cutout: Image.Image,
    backdrop: Image.Image,
    preset: BackdropPreset = DEALER_BACKDROP,
) -> tuple[Image.Image, dict]:
    """
    Place a cut-out vehicle onto a backdrop.

    Returns the finished image and what was done to it, for the job record.
    The cutout is expected to have had its plates treated already: it is
    rescaled here, so any coordinates taken from it beforehand stop being valid.
    """
    cutout = trim_transparent(cutout.convert("RGBA"))
    size = _canvas_size(backdrop, preset)
    canvas = _fit_backdrop(backdrop, size)

    vehicle = _fit_vehicle(cutout, preset, size)
    x, y, ground_y = _vehicle_position(vehicle, preset, size)
    vehicle = match_colour(vehicle, canvas, x, y)

    result = canvas.copy()
    shadowed = preset.placement == "ground"
    if shadowed:
        clip = _platform_mask(preset, size)
        for shadow, position in _shadows(vehicle.getchannel("A"), x, ground_y):
            _composite_clipped(result, shadow, position, clip)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(vehicle, (x, y), vehicle.getchannel("A"))
    result.alpha_composite(layer)

    return result, {
        "backdrop": preset.label,
        "backdrop_style": preset.key,
        "output_size": {"width": size[0], "height": size[1]},
        "ground_aligned": shadowed,
        "shadow_applied": shadowed,
        "colour_matched": True,
    }
