"""Placing a cut-out vehicle into a scene so it reads as photographed in it."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("autopivot.compositing")

BACKGROUND_DIR = Path(__file__).resolve().parent / "assets" / "backgrounds"

MAX_CANVAS_WIDTH = 2400

VehicleAngle = Literal["front", "front_quarter", "side", "rear_quarter", "rear"]

REFERENCE_VEHICLE_ASPECT = 3.14

MAX_WIDTH_OVERRUN = 1.12

MAX_CANVAS_FILL = 0.96

GROUND_LINE_HEADROOM = 0.94

NORMALISE_CLAMP_FLOOR = 0.75


@dataclass(frozen=True)
class BackdropPreset:
    """How a vehicle sits in a particular scene."""

    key: str
    label: str
    filename: str = ""
    placement: str = "ground"
    ground_y_ratio: float = 0.84
    platform_box: tuple[float, float, float, float] | None = None
    platform_contact_y_ratio: float | None = None
    vehicle_width_ratio: float = 0.72
    vehicle_height_ratio: float = 0.60
    reflection_strength: float = 0.0
    output_size: tuple[int, int] | None = None
    backdrop_exposure: float = 1.0


STUDIO_FULL = BackdropPreset(
    key="studio_full",
    label="AutoPivot Studio — Full Car",
    filename="studio-full.png",
    placement="ground",
    ground_y_ratio=0.755,
    platform_box=(0.105, 0.598, 0.875, 0.820),
    platform_contact_y_ratio=0.755,
    vehicle_width_ratio=0.90,
    vehicle_height_ratio=0.58,
    reflection_strength=0.0,
    output_size=(1280, 960),
    backdrop_exposure=0.92,
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
    backdrop_exposure=0.92,
)

STUDIO_PRESETS: dict[str, BackdropPreset] = {
    STUDIO_FULL.key: STUDIO_FULL,
    STUDIO_CLOSEUP.key: STUDIO_CLOSEUP,
}

DEALER_BACKDROP = BackdropPreset(
    key="custom",
    label="Dealership backdrop",
    vehicle_width_ratio=0.80,
    vehicle_height_ratio=0.68,
)


@dataclass(frozen=True)
class _AngleProfile:
    """What the shot angle changes about how a vehicle meets the floor."""

    shadow_depth: float = 1.0
    shadow_width: float = 1.0
    mass_shift: float = 0.0


_NEUTRAL_PROFILE = _AngleProfile()

_ANGLE_PROFILES: dict[str, _AngleProfile] = {
    "front": _AngleProfile(shadow_depth=2.00, shadow_width=1.06),
    "front_quarter": _AngleProfile(shadow_depth=1.30, shadow_width=1.02, mass_shift=0.5),
    "side": _AngleProfile(shadow_depth=0.85, shadow_width=1.00),
    "rear_quarter": _AngleProfile(shadow_depth=1.30, shadow_width=1.02, mass_shift=0.5),
    "rear": _AngleProfile(shadow_depth=2.00, shadow_width=1.06),
}


def _angle_profile(angle: str | None) -> _AngleProfile:
    """The profile for a shot angle, neutral for None or anything unrecognised."""
    if angle is None:
        return _NEUTRAL_PROFILE
    profile = _ANGLE_PROFILES.get(angle)
    if profile is None:
        logger.debug("Unrecognised shot angle '%s'; composing without an angle", angle)
        return _NEUTRAL_PROFILE
    return profile


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


# ── Recognising a dealer's backdrop as one of the built-in scenes ─────────────

_PHASH_SIZE = 8
_PHASH_MATCH_THRESHOLD = 6


def _phash(image: Image.Image) -> int:
    grey = image.convert("L").resize((_PHASH_SIZE, _PHASH_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(grey, dtype=np.float64)
    bits = pixels > pixels.mean()
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _studio_asset_hashes() -> dict[str, int]:
    hashes: dict[str, int] = {}
    for key, preset in STUDIO_PRESETS.items():
        loaded = load_studio_backdrop(key)
        if loaded is not None:
            hashes[key] = _phash(loaded[0])
    return hashes


_STUDIO_ASSET_HASHES: dict[str, int] = _studio_asset_hashes()


def match_studio_backdrop(background: Image.Image) -> BackdropPreset | None:
    """The measured studio preset this background is a copy of, or None."""
    if not _STUDIO_ASSET_HASHES:
        return None
    candidate = _phash(background)
    best_key, best_distance = None, _PHASH_MATCH_THRESHOLD + 1
    for key, reference in _STUDIO_ASSET_HASHES.items():
        distance = _hamming(candidate, reference)
        if distance < best_distance:
            best_key, best_distance = key, distance
    if best_key is None or best_distance > _PHASH_MATCH_THRESHOLD:
        return None
    return STUDIO_PRESETS[best_key]


# ── Mask cleanup ───────────────────────────────────────────────────────────────

_KEEP_COMPONENT_BRIDGE_ALPHA = 128


def _keep_largest_component(alpha: np.ndarray) -> np.ndarray:
    """Zero out every part of the mask except its single largest connected blob."""
    bridge = (alpha > _KEEP_COMPONENT_BRIDGE_ALPHA).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bridge, connectivity=8)
    if count <= 2:
        return alpha
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    keep = (labels == largest_label).astype(np.uint8) * 255
    keep = cv2.dilate(keep, np.ones((5, 5), dtype=np.uint8))
    not_background = (alpha > 16).astype(np.uint8) * 255
    keep = cv2.bitwise_and(keep, not_background)
    return np.where(keep > 0, alpha, 0).astype(np.uint8)


def refine_alpha_mask(mask: Image.Image) -> Image.Image:
    """Tidy a segmentation mask: close pinholes, drop anything that is not the
    vehicle, pull the edge in, feather it."""
    alpha = np.array(mask.convert("L"), dtype=np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    alpha = _keep_largest_component(alpha)
    alpha = cv2.erode(alpha, kernel, iterations=1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.65)
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


# ── Levelling ──────────────────────────────────────────────────────────────────

_LEVELLING_SAFE_ANGLES = frozenset({"front", "rear", "side"})

MAX_LEVEL_CORRECTION_DEGREES = 9.0

LEVELLING_MIN_CONFIDENCE = 0.55

_WHEEL_SEARCH_BAND = 0.42

_WHEEL_RING_DARKNESS_THRESHOLD = 0.40


def _wheel_contacts(vehicle: Image.Image) -> list[tuple[float, float, float]]:
    """Circles found in the lower part of the vehicle's own silhouette that
    plausibly are wheels: (x, y, radius) of each, in the cutout's own pixel
    coordinates."""
    left, top, right, bottom = _visible_bounds(vehicle)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return []

    flat = Image.new("RGB", vehicle.size, (160, 160, 160))
    flat.paste(vehicle, (0, 0), vehicle.getchannel("A"))
    gray = np.array(flat.convert("L"), dtype=np.uint8)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    min_radius = max(4, round(height * 0.07))
    max_radius = max(min_radius + 2, round(height * 0.28))
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(min_radius * 1.5, 12),
        param1=80,
        param2=28,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return []

    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    band_top = top + round(height * (1 - _WHEEL_SEARCH_BAND))
    img_h, img_w = gray.shape
    yy, xx = np.mgrid[0:img_h, 0:img_w]
    found: list[tuple[float, float, float]] = []
    for cx, cy, radius in circles[0]:
        if not (left <= cx <= right and band_top <= cy <= bottom + radius * 0.3):
            continue
        xi, yi = int(round(cx)), int(round(cy))
        if not (0 <= yi < alpha.shape[0] and 0 <= xi < alpha.shape[1]):
            continue
        if alpha[yi, xi] < 96:
            continue
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
        ring = (dist2 <= radius**2) & (dist2 >= (radius * 0.55) ** 2)
        if ring.any() and (gray[ring] < 100).mean() < _WHEEL_RING_DARKNESS_THRESHOLD:
            continue
        found.append((float(cx), float(cy), float(radius)))
    return found


_WHEEL_CLUSTER_X_FRACTION = 0.06


def _outermost_wheel_candidates(
    contacts: list[tuple[float, float, float]], width: int
) -> list[tuple[float, float, float]]:
    """Reduce raw `_wheel_contacts` hits to the single best candidate at each
    horizontal extreme."""
    if not contacts:
        return []
    ordered = sorted(contacts, key=lambda c: c[0])
    if len(ordered) == 1:
        return ordered
    window = width * _WHEEL_CLUSTER_X_FRACTION
    left_x, right_x = ordered[0][0], ordered[-1][0]
    left_group = [c for c in ordered if c[0] - left_x <= window]
    right_group = [c for c in ordered if right_x - c[0] <= window]
    left_best = max(left_group, key=lambda c: c[1] + c[2])
    right_best = max(right_group, key=lambda c: c[1] + c[2])
    if left_best == right_best:
        return [left_best]
    return [left_best, right_best]


def _level_vehicle(
    cutout: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> tuple[Image.Image, float | None]:
    """Rotate a vehicle cutout so its two outermost wheels sit level."""
    if angle not in _LEVELLING_SAFE_ANGLES:
        return cutout, None
    if angle_confidence is not None and angle_confidence < LEVELLING_MIN_CONFIDENCE:
        return cutout, None

    contacts = _outermost_wheel_candidates(_wheel_contacts(cutout), cutout.width)
    if len(contacts) < 2:
        return cutout, None

    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[1]
    if x2 - x1 < cutout.width * 0.15:
        return cutout, None

    angle = math.degrees(math.atan2((y2 + r2) - (y1 + r1), x2 - x1))
    if abs(angle) < 0.5 or abs(angle) > MAX_LEVEL_CORRECTION_DEGREES:
        return cutout, None

    logger.debug("Levelling vehicle by %.2f degrees", angle)
    levelled = cutout.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0)
    )
    return levelled, angle


# ── Quarter-angle ground recession ──────────────────────────────────────────────

_QUARTER_RECEDE_SAFE_ANGLES = frozenset({"front_quarter", "rear_quarter"})

_QUARTER_RECEDE_CORRECTION_FRACTION = 1.0

_QUARTER_RECEDE_TRANSITION_FRACTION = 0.6

_QUARTER_RECEDE_MAX_FRACTION = 0.40

_QUARTER_RECEDE_MIN_GAP_PX = 3.0


def _recede_quarter_ground(
    cutout: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> tuple[Image.Image, float | None]:
    """Close a quarter-angle photograph's near/far wheel gap by warping only
    the lower band of the cutout, rather than rotating it."""
    if angle not in _QUARTER_RECEDE_SAFE_ANGLES:
        return cutout, None
    if angle_confidence is not None and angle_confidence < LEVELLING_MIN_CONFIDENCE:
        logger.info("[QDIAG] recede declined: confidence %.2f below bar", angle_confidence)
        return cutout, None

    raw_contacts = _wheel_contacts(cutout)
    logger.info("[QDIAG] recede angle=%s wheel_contacts=%s", angle, raw_contacts)
    contacts = _outermost_wheel_candidates(raw_contacts, cutout.width)
    if len(contacts) < 2:
        logger.info("[QDIAG] recede declined: fewer than 2 wheels found")
        return cutout, None
    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[1]
    logger.info(
        "[QDIAG] recede outermost candidates: (%.1f,%.1f,%.1f) (%.1f,%.1f,%.1f)",
        x1, y1, r1, x2, y2, r2,
    )
    if x2 - x1 < cutout.width * 0.15:
        logger.info(
            "[QDIAG] recede declined: candidates too close (%.1f vs cutout width %d)",
            x2 - x1, cutout.width,
        )
        return cutout, None

    c1, c2 = y1 + r1, y2 + r2
    if c1 >= c2:
        near_x, far_x, far_top, far_r = x1, x2, y2 - r2, r2
        gap = c1 - c2
    else:
        near_x, far_x, far_top, far_r = x2, x1, y1 - r1, r1
        gap = c2 - c1
    if gap < _QUARTER_RECEDE_MIN_GAP_PX:
        logger.info("[QDIAG] recede declined: gap %.1fpx negligible", gap)
        return cutout, None

    _, top, _, bottom = _visible_bounds(cutout)
    height = max(1, bottom - top)
    if gap > height * _QUARTER_RECEDE_MAX_FRACTION:
        logger.info(
            "[QDIAG] recede declined: gap %.1fpx implausible for height %d", gap, height
        )
        return cutout, None

    correction = gap * _QUARTER_RECEDE_CORRECTION_FRACTION
    transition = max(1.0, far_r * _QUARTER_RECEDE_TRANSITION_FRACTION)
    band_top = far_top - transition
    warped = _warp_recede(cutout, near_x, far_x, correction, band_top, far_top)
    logger.info(
        "[QDIAG] recede applied: near_x=%.1f far_x=%.1f far_r=%.1f gap=%.1f correction=%.1f "
        "cutout_size_before=%s cutout_size_after=%s",
        near_x, far_x, far_r, gap, correction, cutout.size, warped.size,
    )
    return warped, float(correction)


def _warp_recede(
    cutout: Image.Image,
    near_x: float,
    far_x: float,
    correction: float,
    band_top: float,
    full_at: float,
) -> Image.Image:
    """Shift the lower band of `cutout` down by up to `correction` pixels on
    the far side, tapering to zero at `near_x` and above `band_top`."""
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    rgb = np.array(cutout.convert("RGB"), dtype=np.uint8)
    h, w = alpha.shape

    pad = int(math.ceil(correction)) + 2
    padded_h = h + pad

    xs = np.arange(w, dtype=np.float32)
    if near_x == far_x:
        return cutout
    t = np.clip((xs - far_x) / (near_x - far_x), 0.0, 1.0)
    horiz_shift = correction * (1.0 - t)

    ys = np.arange(padded_h, dtype=np.float32)
    reach = max(1.0, full_at - band_top)
    vert_taper = np.clip((ys - band_top) / reach, 0.0, 1.0)

    shift_grid = horiz_shift[None, :] * vert_taper[:, None]
    map_x = np.tile(xs[None, :], (padded_h, 1))
    map_y = np.tile(ys[:, None], (1, w)) - shift_grid

    remapped_alpha = cv2.remap(
        alpha, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    remapped_rgb = cv2.remap(
        rgb, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    result = Image.fromarray(remapped_rgb, mode="RGB").convert("RGBA")
    result.putalpha(Image.fromarray(remapped_alpha, mode="L"))
    return result


# ── Geometry ───────────────────────────────────────────────────────────────────

def _visible_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha > 6)
    if xs.size == 0 or ys.size == 0:
        return 0, 0, image.width, image.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


_CONTACT_SOLID_ALPHA = 128

_CONTACT_SOFT_ALPHA = 32

_CONTACT_MAX_SOFT_EXTENSION = 15


def _contact_y(
    vehicle: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> int:
    """The line the tyres sit on."""
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid = alpha >= _CONTACT_SOLID_ALPHA
    soft = alpha >= _CONTACT_SOFT_ALPHA

    bottoms: list[int] = []
    for x in range(alpha.shape[1]):
        edge = _capped_soft_edge(solid[:, x], soft[:, x])
        if edge is not None:
            bottoms.append(edge)

    if not bottoms:
        naive = _visible_bounds(vehicle)[3]
        logger.info("[QDIAG] contact_y angle=%s: no columns had solid pixels, using naive=%d", angle, naive)
        return naive
    bottoms_arr = np.asarray(bottoms, dtype=np.float32)
    contact = int(round(float(np.quantile(bottoms_arr, 0.97))))
    naive_bottom = _visible_bounds(vehicle)[3]
    logger.info(
        "[QDIAG] contact_y angle=%s: quantile=%d naive_bottom=%d vehicle_size=%s "
        "columns_with_contact=%d/%d",
        angle, contact, naive_bottom, vehicle.size, len(bottoms), vehicle.size[0],
    )

    return contact


_CONTACT_WHEEL_CAP_MAX_FRACTION = 0.35


def _wheel_grounded_contact_cap(vehicle: Image.Image) -> int | None:
    """An upper bound on `_contact_y`'s ground-contact row, taken from the two
    outermost detected wheels rather than an alpha threshold."""
    contacts = _outermost_wheel_candidates(_wheel_contacts(vehicle), vehicle.width)
    if len(contacts) < 2:
        return None
    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[1]
    if x2 - x1 < vehicle.width * 0.15:
        return None

    _, top, _, bottom = _visible_bounds(vehicle)
    height = max(1, bottom - top)
    shallow = min(y1 + r1, y2 + r2)
    deep = max(y1 + r1, y2 + r2)
    if (deep - shallow) > height * _CONTACT_WHEEL_CAP_MAX_FRACTION:
        return None
    return int(round(shallow))


def _capped_soft_edge(has_solid: np.ndarray, has_soft: np.ndarray) -> int | None:
    """Shared by `_contact_y` and `_shadow_capped_bottom`: the deepest index
    that should count as the real edge of the object, or None if there is no
    solid content at all."""
    solid_idx = np.flatnonzero(has_solid)
    if not solid_idx.size:
        return None
    solid_edge = int(solid_idx[-1])
    soft_idx = np.flatnonzero(has_soft)
    soft_edge = int(soft_idx[-1]) if soft_idx.size else solid_edge
    return min(soft_edge, solid_edge + _CONTACT_MAX_SOFT_EXTENSION)


def _shadow_capped_bottom(vehicle: Image.Image) -> int | None:
    """The vehicle's own lowest row, for sizing rather than ground placement."""
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid_rows = (alpha >= _CONTACT_SOLID_ALPHA).any(axis=1)
    soft_rows = (alpha >= _CONTACT_SOFT_ALPHA).any(axis=1)
    return _capped_soft_edge(solid_rows, soft_rows)


def _shadow_capped_side(vehicle: Image.Image, *, leading: bool) -> int | None:
    """The vehicle's own left or right edge, for sizing rather than ground
    placement."""
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid_cols = (alpha >= _CONTACT_SOLID_ALPHA).any(axis=0)
    soft_cols = (alpha >= _CONTACT_SOFT_ALPHA).any(axis=0)
    if leading:
        solid_cols, soft_cols = solid_cols[::-1], soft_cols[::-1]
    edge = _capped_soft_edge(solid_cols, soft_cols)
    if edge is None:
        return None
    return len(solid_cols) - 1 - edge if leading else edge


_MAX_WHEEL_PATCH_FRACTION = 0.35


def _patch_wheel_gaps(vehicle: Image.Image) -> Image.Image:
    """Extend a wheel's mask up to its own detected circle where the cutout's
    alpha falls short of it."""
    contacts = _wheel_contacts(vehicle)
    if not contacts:
        return vehicle

    outermost = _outermost_wheel_candidates(contacts, vehicle.width)
    if len(outermost) >= 2 and outermost[-1][0] - outermost[0][0] >= vehicle.width * 0.15:
        contacts = outermost
    else:
        contacts = [max(contacts, key=lambda c: c[2])]

    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    rgb = np.array(vehicle.convert("RGB"), dtype=np.uint8)
    height, width = alpha.shape
    patched_any = False

    for cx, cy, radius in contacts:
        cx_i, cy_i, r_i = int(round(cx)), int(round(cy)), int(round(radius))
        x0, x1 = max(0, cx_i - r_i), min(width, cx_i + r_i + 1)
        y0, y1 = max(0, cy_i - r_i), min(height, cy_i + r_i + 1)
        if x1 <= x0 or y1 <= y0 or not (0 <= cx_i < width):
            continue

        column = alpha[y0:y1, cx_i]
        opaque_rows = np.flatnonzero(column >= 32)
        visible_bottom = y0 + int(opaque_rows[-1]) if opaque_rows.size else cy_i
        missing = (cy_i + r_i) - visible_bottom
        if missing <= 0 or missing > radius * _MAX_WHEEL_PATCH_FRACTION:
            continue

        yy, xx = np.mgrid[y0:y1, x0:x1]
        disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
        window_alpha = alpha[y0:y1, x0:x1]
        opaque = window_alpha >= 32
        gap = disc & ~opaque
        if not gap.any():
            continue

        tyre_pixels = rgb[y0:y1, x0:x1][disc & opaque]
        if tyre_pixels.size == 0:
            continue
        fill_colour = np.median(tyre_pixels.reshape(-1, 3), axis=0)

        window_rgb = rgb[y0:y1, x0:x1]
        window_rgb[gap] = fill_colour
        window_alpha[gap] = 255
        patched_any = True

    if not patched_any:
        return vehicle

    result = Image.fromarray(rgb, "RGB").convert("RGBA")
    softened = cv2.GaussianBlur(alpha, (0, 0), 0.6)
    result.putalpha(Image.fromarray(softened, "L"))
    return result


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


def _apply_backdrop_exposure(canvas: Image.Image, factor: float) -> Image.Image:
    """Scale the backdrop's RGB by `factor`, alpha untouched. `factor == 1.0` is a no-op."""
    if factor == 1.0:
        return canvas
    array = np.array(canvas.convert("RGBA"), dtype=np.float32)
    array[:, :, :3] = np.clip(array[:, :, :3] * factor, 0, 255)
    return Image.fromarray(array.astype(np.uint8), mode="RGBA")


def _fit_vehicle(
    cutout: Image.Image,
    preset: BackdropPreset,
    size: tuple[int, int],
    ground_y: int | None = None,
) -> tuple[Image.Image, bool]:
    """Scale the cutout to the scene. Returns the vehicle and whether height
    normalisation was used rather than the older fill-the-box rule."""
    canvas_w, canvas_h = size
    if preset.platform_box:
        platform_width = canvas_w * (preset.platform_box[2] - preset.platform_box[0])
        max_width = platform_width * preset.vehicle_width_ratio
        limit_width = min(platform_width, max_width * MAX_WIDTH_OVERRUN)
    else:
        max_width = canvas_w * preset.vehicle_width_ratio
        limit_width = min(canvas_w * MAX_CANVAS_FILL, max_width * MAX_WIDTH_OVERRUN)
    max_height = canvas_h * preset.vehicle_height_ratio
    limit_height = canvas_h * MAX_CANVAS_FILL

    if ground_y is not None:
        headroom = ground_y * GROUND_LINE_HEADROOM
        max_height = min(max_height, headroom)
        limit_height = min(limit_height, headroom)

    fill_scale = min(max_width / cutout.width, max_height / cutout.height)
    scale, normalised = fill_scale, False

    left, top, right, bottom = _visible_bounds(cutout)
    capped_bottom = _shadow_capped_bottom(cutout)
    if capped_bottom is not None:
        bottom = min(bottom, capped_bottom + 1)
    capped_left = _shadow_capped_side(cutout, leading=True)
    if capped_left is not None:
        left = max(left, capped_left)
    capped_right = _shadow_capped_side(cutout, leading=False)
    if capped_right is not None:
        right = min(right, capped_right + 1)
    visible_w, visible_h = right - left, bottom - top
    if visible_w > 0 and visible_h > 0:
        target_height = min(max_height, max_width / REFERENCE_VEHICLE_ASPECT)
        candidate = target_height / visible_h

        clamped = min(
            candidate,
            limit_width / visible_w,
            limit_height / visible_h,
        )

        if clamped >= candidate * NORMALISE_CLAMP_FLOOR:
            scale, normalised = clamped, True

    return (
        cutout.resize(
            (max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))),
            Image.Resampling.LANCZOS,
        ),
        normalised,
    )


def _mass_skew(vehicle: Image.Image) -> float:
    """How far the silhouette's weight sits from the middle of its bounding
    box, as a fraction of the bounding box's width. Positive means weight to the right."""
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    columns = alpha.sum(axis=0, dtype=np.float64)
    total = columns.sum()
    left, _, right, _ = _visible_bounds(vehicle)
    width = right - left
    if total <= 0 or width <= 0:
        return 0.0
    centroid = float((columns * np.arange(columns.size, dtype=np.float64)).sum() / total)
    return (centroid - (left + right) / 2.0) / width


def _ground_line(preset: BackdropPreset, canvas_h: int) -> int:
    """The floor's y-coordinate on the canvas, independent of any particular vehicle."""
    ratio = (
        preset.platform_contact_y_ratio
        if preset.platform_contact_y_ratio is not None
        else preset.ground_y_ratio
    )
    return round(canvas_h * ratio)


def _vehicle_position(
    vehicle: Image.Image,
    preset: BackdropPreset,
    size: tuple[int, int],
    profile: _AngleProfile = _NEUTRAL_PROFILE,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> tuple[int, int, int]:
    """Return where to paste the vehicle, and the y of the ground line."""
    canvas_w, canvas_h = size
    left, top, right, bottom = _visible_bounds(vehicle)

    skew = _mass_skew(vehicle) * profile.mass_shift if profile.mass_shift else 0.0
    offset = skew * (right - left)

    if preset.platform_box:
        platform_left = canvas_w * preset.platform_box[0]
        platform_right = canvas_w * preset.platform_box[2]
        platform_centre_x = (platform_left + platform_right) / 2
        x = round(platform_centre_x - (left + right) / 2 + offset)

        vehicle_width = right - left
        if vehicle_width <= platform_right - platform_left:
            x = max(x, round(platform_left - left))
            x = min(x, round(platform_right - right))
    else:
        x = round(canvas_w / 2 - (left + right) / 2 + offset)

    if preset.placement == "center":
        y = round(canvas_h * 0.52 - (top + bottom) / 2)
        return int(x), int(y), min(canvas_h - 1, int(y + bottom))

    contact = (
        _contact_y(vehicle, angle, angle_confidence) if preset.platform_box else bottom
    )
    ground_y = _ground_line(preset, canvas_h)
    paste_y = int(round(ground_y - contact))
    logger.info(
        "[QDIAG] vehicle_position angle=%s: contact=%d ground_y=%d paste_y=%d "
        "vehicle_bottom_on_canvas=%d (should equal ground_y=%d)",
        angle, contact, ground_y, paste_y, paste_y + contact, ground_y,
    )
    return int(x), paste_y, int(ground_y)


def _platform_mask(
    preset: BackdropPreset, size: tuple[int, int], feather: float = 0.0
) -> Image.Image | None:
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
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
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
    """Squash the vehicle's own silhouette into a shadow on the floor."""
    source = alpha.convert("L")
    width = max(1, round(source.width * width_scale))
    height = max(4, round(source.height * height_ratio))
    compressed = source.resize((width, height), Image.Resampling.LANCZOS)

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
    alpha: Image.Image,
    vehicle_x: int,
    ground_y: int,
    profile: _AngleProfile = _NEUTRAL_PROFILE,
) -> list[tuple[Image.Image, tuple[int, int]]]:
    """Ambient pool first, then the tighter darker contact shadow over it."""
    height = max(1, alpha.height)
    return [
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.14, max(8.0, height * 0.045), 0.14 * profile.shadow_depth, 1.04 * profile.shadow_width,
        ),
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.32, max(4.0, height * 0.0225), 0.075 * profile.shadow_depth, 0.90 * profile.shadow_width,
        ),
    ]


# ── Per-wheel contact pools ──────────────────────────────────────────────────

_WHEEL_CONTACT_OPACITY = 0.38

_WHEEL_CONTACT_BLUR_RATIO = 0.20

_WHEEL_CONTACT_WIDTH_RATIO = 1.3
_WHEEL_CONTACT_HEIGHT_RATIO = 0.4


def _build_wheel_contact_shadow(radius: float, opacity: float, blur: float) -> Image.Image:
    """A small, soft, dark ellipse sized off one wheel's own radius."""
    half_w = max(2, round(radius * _WHEEL_CONTACT_WIDTH_RATIO))
    half_h = max(2, round(radius * _WHEEL_CONTACT_HEIGHT_RATIO))
    padding = max(2, round(blur * 2))
    size = (half_w * 2 + padding * 2, half_h * 2 + padding * 2)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(
        (padding, padding, padding + half_w * 2, padding + half_h * 2),
        fill=round(255 * opacity),
    )
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.putalpha(mask)
    return shadow


_WHEEL_CONTACT_ROW_QUANTILE = 0.9


def _wheel_contact_row(vehicle: Image.Image, cx: float, radius: float) -> int | None:
    """Return the true ground-contact row for one wheel."""
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    height, width = alpha.shape
    x0 = max(0, int(round(cx - radius)))
    x1 = min(width, int(round(cx + radius)) + 1)
    if x1 <= x0:
        return None
    solid = alpha >= _CONTACT_SOLID_ALPHA
    soft = alpha >= _CONTACT_SOFT_ALPHA
    bottoms: list[int] = []
    for x in range(x0, x1):
        edge = _capped_soft_edge(solid[:, x], soft[:, x])
        if edge is not None:
            bottoms.append(edge)
    if not bottoms:
        return None
    return int(round(float(np.quantile(np.asarray(bottoms, dtype=np.float32), _WHEEL_CONTACT_ROW_QUANTILE))))


def _wheel_contact_shadows(
    vehicle: Image.Image, vehicle_x: int, vehicle_y: int
) -> list[tuple[Image.Image, tuple[int, int]]]:
    """One small dark contact pool per wheel found, positioned at that wheel's
    own bottom edge on the canvas."""
    layers: list[tuple[Image.Image, tuple[int, int]]] = []
    for cx, cy, radius in _outermost_wheel_candidates(_wheel_contacts(vehicle), vehicle.width):
        blur = max(1.5, radius * _WHEEL_CONTACT_BLUR_RATIO)
        shadow = _build_wheel_contact_shadow(radius, _WHEEL_CONTACT_OPACITY, blur)
        contact_row = _wheel_contact_row(vehicle, cx, radius)
        ground_row = cy + radius if contact_row is None else contact_row
        centre_x = vehicle_x + round(cx)
        centre_y = vehicle_y + round(ground_row)
        layers.append((shadow, (centre_x - shadow.width // 2, centre_y - shadow.height // 2)))
    return layers


# ── Reflection ─────────────────────────────────────────────────────────────────

REFLECTION_SQUASH = 0.42


def _build_reflection(
    vehicle: Image.Image, contact_y: int, strength: float, blur: float
) -> Image.Image | None:
    """A soft mirror image of the vehicle, to be placed with its top on the
    contact line. None when there is nothing worth reflecting."""
    if strength <= 0:
        return None
    contact_y = min(contact_y, vehicle.height)
    if contact_y < 8:
        return None

    mirrored = vehicle.crop((0, 0, vehicle.width, contact_y)).transpose(
        Image.Transpose.FLIP_TOP_BOTTOM
    )
    height = max(4, round(mirrored.height * REFLECTION_SQUASH))
    mirrored = mirrored.resize((mirrored.width, height), Image.Resampling.LANCZOS)

    alpha = np.array(mirrored.getchannel("A"), dtype=np.float32)
    fade = (1.0 - np.linspace(0.0, 1.0, height, dtype=np.float32)) ** 1.6
    alpha *= strength * fade[:, None]

    faded = Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), mode="L")
    if blur > 0:
        faded = faded.filter(ImageFilter.GaussianBlur(blur))
    mirrored.putalpha(faded)
    return mirrored


def _reflects(preset: BackdropPreset) -> bool:
    """Whether this scene gets a reflection."""
    return (
        preset.reflection_strength > 0
        and preset.placement == "ground"
        and preset.platform_box is not None
    )


def _placement(
    layer_size: tuple[int, int], position: tuple[int, int], canvas_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], tuple[int, int]] | None:
    """Where a layer actually lands, once any overhang is cropped away, or
    None when the layer misses the canvas entirely."""
    layer_w, layer_h = layer_size
    canvas_w, canvas_h = canvas_size
    x, y = position

    left, top = max(0, -x), max(0, -y)
    if left >= layer_w or top >= layer_h:
        return None

    x, y = max(0, x), max(0, y)
    if x >= canvas_w or y >= canvas_h:
        return None

    right = min(layer_w, left + canvas_w - x)
    bottom = min(layer_h, top + canvas_h - y)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom), (x, y)


def _alpha_composite_at(
    canvas: Image.Image, layer: Image.Image, position: tuple[int, int]
) -> None:
    """alpha_composite that tolerates a layer hanging off any edge."""
    placed = _placement(layer.size, position, canvas.size)
    if placed is None:
        return
    box, destination = placed
    if box != (0, 0, layer.width, layer.height):
        layer = layer.crop(box)
    canvas.alpha_composite(layer, destination)


def _composite_clipped(
    canvas: Image.Image,
    layer: Image.Image,
    position: tuple[int, int],
    clip: Image.Image | None,
) -> None:
    """Composite a layer with its alpha multiplied by a full-canvas clip mask."""
    if clip is None:
        _alpha_composite_at(canvas, layer, position)
        return

    placed = _placement(layer.size, position, canvas.size)
    if placed is None:
        return
    box, (x, y) = placed
    patch = layer.crop(box)

    patch_alpha = np.array(patch.getchannel("A"), dtype=np.float32)
    clip_alpha = np.array(
        clip.crop((x, y, x + patch.width, y + patch.height)), dtype=np.float32
    ) / 255.0
    patch.putalpha(
        Image.fromarray(np.clip(patch_alpha * clip_alpha, 0, 255).astype(np.uint8), mode="L")
    )
    canvas.alpha_composite(patch, (x, y))


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


def _ambient_patch(backdrop: Image.Image) -> np.ndarray:
    """A sample of the scene's own ambient light — its wall and ceiling —
    rather than the region immediately behind where the vehicle will stand."""
    band_bottom = max(1, round(backdrop.height * 0.35))
    return np.array(
        backdrop.crop((0, 0, backdrop.width, band_bottom)).convert("RGB"),
        dtype=np.uint8,
    )


CONTRAST_MATCH_STRENGTH = 0.6
CONTRAST_MATCH_CLAMP = 0.18


def match_colour(
    vehicle: Image.Image, backdrop: Image.Image, x: int, y: int,
    *, placement: str = "center",
) -> Image.Image:
    """Nudge the vehicle towards the scene's lighting. Weak and clamped on purpose."""
    rgba = np.array(vehicle.convert("RGBA"), dtype=np.uint8)
    opaque = rgba[:, :, 3] > 24
    patch = (
        _ambient_patch(backdrop) if placement == "ground"
        else _backdrop_patch(backdrop, x, y, vehicle.width, vehicle.height)
    )
    if not np.any(opaque) or patch.size == 0:
        return vehicle

    vehicle_lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    backdrop_lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    vehicle_mean = vehicle_lab[opaque].mean(axis=0)
    backdrop_mean = backdrop_lab.reshape(-1, 3).mean(axis=0)

    vehicle_lightness_std = float(vehicle_lab[opaque][:, 0].std())
    if vehicle_lightness_std > 1.0:
        backdrop_lightness_std = float(backdrop_lab[:, :, 0].std())
        relative_gap = (backdrop_lightness_std - vehicle_lightness_std) / vehicle_lightness_std
        contrast_scale = 1.0 + np.clip(
            relative_gap, -CONTRAST_MATCH_CLAMP, CONTRAST_MATCH_CLAMP
        ) * CONTRAST_MATCH_STRENGTH
        vehicle_lab[:, :, 0] = (
            vehicle_mean[0] + (vehicle_lab[:, :, 0] - vehicle_mean[0]) * contrast_scale
        )

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
    *,
    angle: VehicleAngle | str | None = None,
    angle_confidence: float | None = None,
) -> tuple[Image.Image, dict]:
    """Place a cut-out vehicle onto a backdrop. Returns the finished image and
    what was done to it, for the job record."""
    cutout = trim_transparent(cutout.convert("RGBA"))
    levelled, level_angle = _level_vehicle(cutout, angle, angle_confidence)
    cutout = trim_transparent(levelled)
    cutout = _patch_wheel_gaps(cutout)
    receded, recede_px = _recede_quarter_ground(cutout, angle, angle_confidence)
    cutout = trim_transparent(receded)
    size = _canvas_size(backdrop, preset)
    canvas = _fit_backdrop(backdrop, size)
    canvas = _apply_backdrop_exposure(canvas, preset.backdrop_exposure)
    profile = _angle_profile(angle)

    ground_hint = _ground_line(preset, size[1]) if preset.placement == "ground" else None
    vehicle, normalised = _fit_vehicle(cutout, preset, size, ground_y=ground_hint)
    x, y, ground_y = _vehicle_position(vehicle, preset, size, profile, angle, angle_confidence)
    vehicle = match_colour(vehicle, canvas, x, y, placement=preset.placement)

    result = canvas.copy()
    shadowed = preset.placement == "ground"
    reflected = False
    if shadowed:
        clip = _platform_mask(preset, size)
        if _reflects(preset):
            reflection = _build_reflection(
                vehicle,
                ground_y - y,
                preset.reflection_strength,
                blur=max(1.0, size[1] * 0.0035),
            )
            if reflection is not None:
                _composite_clipped(
                    result,
                    reflection,
                    (x, ground_y),
                    _platform_mask(preset, size, feather=size[1] * 0.006),
                )
                reflected = True
        for shadow, position in _shadows(vehicle.getchannel("A"), x, ground_y, profile):
            _composite_clipped(result, shadow, position, clip)
        for shadow, position in _wheel_contact_shadows(vehicle, x, y):
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
        "shot_angle": angle,
        "height_normalised": normalised,
        "reflection_applied": reflected,
        "levelled_degrees": level_angle,
        "quarter_ground_correction_px": recede_px,
    }
