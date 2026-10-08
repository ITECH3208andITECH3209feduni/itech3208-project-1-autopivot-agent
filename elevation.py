"""Estimating the camera elevation of a source photograph, from the cutout alone."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("autopivot.elevation")

ELEVATION_METHODS = ("wheel_ellipse", "roof_underside", "shot_angle", "assumed")

MEASURED_METHODS = ("wheel_ellipse", "roof_underside")


# ── The vehicle this module assumes ────────────────────────────────────────────

WHEEL_DIAMETER_M = 0.632

WHEEL_CENTRE_HEIGHT_M = WHEEL_DIAMETER_M / 2.0

REFERENCE_VEHICLE_LENGTH_M = 4.70
REFERENCE_VEHICLE_WIDTH_M = 1.83
REFERENCE_VEHICLE_HEIGHT_M = 1.45

TYPICAL_SHOOTING_DISTANCE_M = 6.0

CROUCHING_CAMERA_HEIGHT_M = 0.80
STANDING_CAMERA_HEIGHT_M = 1.50
RAISED_CAMERA_HEIGHT_M = 2.20


def _elevation_for_camera_height(camera_height_m: float) -> float:
    """The elevation a camera at this height sees the wheel centre at, in degrees."""
    return math.degrees(
        math.atan2(camera_height_m - WHEEL_CENTRE_HEIGHT_M, TYPICAL_SHOOTING_DISTANCE_M)
    )


def camera_height_for_elevation(elevation_deg: float) -> float:
    """How high the camera stood, in metres, to see the wheel centre at this angle."""
    return WHEEL_CENTRE_HEIGHT_M + TYPICAL_SHOOTING_DISTANCE_M * math.tan(
        math.radians(elevation_deg)
    )


CROUCHING_ELEVATION_DEG = _elevation_for_camera_height(CROUCHING_CAMERA_HEIGHT_M)  # 4.61
STANDING_ELEVATION_DEG = _elevation_for_camera_height(STANDING_CAMERA_HEIGHT_M)    # 11.16
RAISED_ELEVATION_DEG = _elevation_for_camera_height(RAISED_CAMERA_HEIGHT_M)        # 17.43


# ── The plausible range ────────────────────────────────────────────────────────

MIN_ELEVATION_DEG = -5.0
MAX_ELEVATION_DEG = 35.0

OUT_OF_RANGE_TOLERANCE_DEG = 3.0


# ── Confidence policy ──────────────────────────────────────────────────────────

CONFIDENCE_REFERENCE_SIGMA_DEG = 5.0

WHEEL_CONFIDENCE_CEILING = 0.55
UNDERSIDE_CONFIDENCE_CEILING = 0.35
ANGLE_PRIOR_CONFIDENCE_NAMED = 0.20
ANGLE_PRIOR_CONFIDENCE_OTHER = 0.15
ASSUMED_CONFIDENCE = 0.10

MIN_USEFUL_CONFIDENCE = 0.12

AZIMUTH_ASSUMED_PENALTY = 0.6


# ── Rung 1: the wheel ellipse ──────────────────────────────────────────────────

WHEEL_SEARCH_BAND = 0.55

TYRE_LIGHTNESS_PERCENTILE = 0.15
TYRE_LIGHTNESS_CEILING = 96  # LAB L, 0-255

TYRE_SATURATION_MAX = 64  # HSV S, 0-255

WHEEL_MAJOR_MIN_RATIO = 0.25
WHEEL_MAJOR_MAX_RATIO = 0.62

WHEEL_MIN_MAJOR_PX = 160

WHEEL_CHORD_FRACTIONS = (0.70, 0.80, 0.90, 0.95)

WHEEL_RATIO_SPREAD_MAX = 0.06

TYRE_CONTACT_TOLERANCE = 0.02

SIDE_AZIMUTH_TOLERANCE_DEG = 10.0

RATIO_SIGMA_PERSPECTIVE = 0.02

_CHORD_SIGMA_PIXELS = 3.6


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

UNDERSIDE_GEOMETRY: dict[str, tuple[float, float]] = {
    "side": (0.16, 0.105),
    "quarter": (0.21, 0.48),
    "end": (0.25, 0.85),
}

CLEARANCE_UNCERTAINTY_M = 0.05

ASPECT_END_MAX = 2.2

UNDERSIDE_BOTTOM_FLAT_MAX = 0.55

UNDERSIDE_CONTACT_TOLERANCE = 0.01

UNDERSIDE_MIN_SILHOUETTE_PX = 64

UNDERSIDE_MIN_WHEELBASE_RATIO = 0.20


# ── Rung 3: the population prior ───────────────────────────────────────────────

ANGLE_ELEVATION_PRIOR_DEG: dict[str, float] = {
    "front_quarter": CROUCHING_ELEVATION_DEG,
    "side": STANDING_ELEVATION_DEG,
    "rear": RAISED_ELEVATION_DEG,
    "front": STANDING_ELEVATION_DEG,
    "rear_quarter": (STANDING_ELEVATION_DEG + RAISED_ELEVATION_DEG) / 2.0,
}

_PLAN_NAMED_ANGLES = ("front_quarter", "side", "rear")


@dataclass(frozen=True)
class ElevationEstimate:
    """What the cascade concluded about where the camera was."""

    degrees: float
    confidence: float
    method: str


# ── Shared geometry helpers ────────────────────────────────────────────────────

def _visible_bounds(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
    """The bounding box of anything visible, or None for an empty cutout."""
    ys, xs = np.where(alpha > 6)
    if xs.size == 0 or ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _column_bottoms(solid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every column, whether it holds anything solid and its lowest solid row."""
    has = solid.any(axis=0)
    lowest = (solid.shape[0] - 1) - np.argmax(solid[::-1, :], axis=0)
    return has, lowest


def _contact_line(solid: np.ndarray) -> float | None:
    """The row the tyres sit on."""
    has, lowest = _column_bottoms(solid)
    if not has.any():
        return None
    return float(np.quantile(lowest[has].astype(np.float64), 0.97))


def _clamped_to_range(theta_deg: float) -> tuple[float, float] | None:
    """A rung's raw answer brought inside the plausible range, with the confidence
    factor that costs, or None when it must be thrown away instead.
    """
    if not math.isfinite(theta_deg):
        return None
    if MIN_ELEVATION_DEG <= theta_deg <= MAX_ELEVATION_DEG:
        return theta_deg, 1.0
    if not (
        MIN_ELEVATION_DEG - OUT_OF_RANGE_TOLERANCE_DEG
        <= theta_deg
        <= MAX_ELEVATION_DEG + OUT_OF_RANGE_TOLERANCE_DEG
    ):
        return None
    return min(max(theta_deg, MIN_ELEVATION_DEG), MAX_ELEVATION_DEG), 0.5


def _confidence_from_sigma(ceiling: float, sigma_theta_deg: float, quality: float) -> float:
    """A rung's confidence, propagated from its own error budget rather than asserted.
    """
    if not math.isfinite(sigma_theta_deg) or sigma_theta_deg <= 0:
        return 0.0
    resolved = min(1.0, CONFIDENCE_REFERENCE_SIGMA_DEG / sigma_theta_deg)
    return float(ceiling * resolved * quality)


# ── Rung 1: wheel ellipse ──────────────────────────────────────────────────────

def _chord_ratio(contour: np.ndarray) -> tuple[float, float] | None:
    """A tyre's minor-over-major axis ratio, measured from its sides and bottom only.
    Returns (ratio, major_px), or None when the arc could not be sampled.
    """
    x, y, width, height = cv2.boundingRect(contour)
    if width < 2 or height < 2:
        return None

    filled = np.zeros((height, width), dtype=np.uint8)
    cv2.drawContours(filled, [contour - np.array([[x, y]])], -1, 1, thickness=-1)

    occupied = filled.any(axis=1)
    if not occupied.any():
        return None
    first = np.argmax(filled, axis=1)
    last = (width - 1) - np.argmax(filled[:, ::-1], axis=1)
    widths = np.where(occupied, (last - first + 1).astype(np.float64), 0.0)

    major = float(widths.max())
    if major < 2:
        return None
    lowest_row = int(np.flatnonzero(occupied)[-1])
    highest_row = int(np.flatnonzero(occupied)[0])
    bottom = lowest_row + 0.5

    semi_minor: list[float] = []
    for fraction in WHEEL_CHORD_FRACTIONS:
        target = fraction * major
        crossing = None
        for row in range(lowest_row, highest_row - 1, -1):
            if widths[row] < target:
                continue
            below = widths[row + 1] if row < lowest_row else 0.0
            crossing = (row + 1) - (target - below) / (widths[row] - below)
            break
        if crossing is None:
            continue
        chord = 1.0 - math.sqrt(max(0.0, 1.0 - fraction * fraction))
        candidate = (bottom - crossing) / chord
        if candidate > 0:
            semi_minor.append(candidate)

    if len(semi_minor) < len(WHEEL_CHORD_FRACTIONS) - 1:
        return None
    return float(np.median(semi_minor)) / (major / 2.0), major


def _wheel_ellipse(cutout: Image.Image, angle: str | None) -> ElevationEstimate | None:
    """Elevation from the foreshortening of the tyres, or None when it cannot be had."""
    if angle != "side":
        return None

    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    bounds = _visible_bounds(alpha)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    height, width = bottom - top, right - left

    solid = alpha >= 128
    contact = _contact_line(solid)
    if contact is None:
        return None

    band_top = max(top, int(round(bottom - WHEEL_SEARCH_BAND * height)))
    searched = np.zeros_like(solid)
    searched[band_top:bottom, left:right] = True
    searched &= solid
    if not searched.any():
        return None

    rgb = np.array(cutout.convert("RGB"), dtype=np.uint8)
    lightness = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 0]
    saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]

    ceiling = min(
        float(TYRE_LIGHTNESS_CEILING),
        float(np.percentile(lightness[searched], TYRE_LIGHTNESS_PERCENTILE * 100.0)),
    )
    tyre = searched & (saturation < TYRE_SATURATION_MAX) & (lightness < ceiling)

    opened = cv2.morphologyEx(
        tyre.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )
    contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    candidates: list[tuple[float, float]] = []
    for contour in contours:
        _, box_top, box_width, box_height = cv2.boundingRect(contour)
        if not WHEEL_MAJOR_MIN_RATIO * height <= box_width <= WHEEL_MAJOR_MAX_RATIO * height:
            continue
        if box_width < WHEEL_MIN_MAJOR_PX:
            continue
        if box_top <= band_top:
            continue
        if abs((box_top + box_height - 1) - contact) > TYRE_CONTACT_TOLERANCE * height:
            continue
        measured = _chord_ratio(contour)
        if measured is None:
            continue
        candidates.append(measured)

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[1], reverse=True)
    accepted = candidates[:2]

    if len(accepted) == 2 and abs(accepted[0][0] - accepted[1][0]) > WHEEL_RATIO_SPREAD_MAX:
        return None

    ratio = float(np.median([item[0] for item in accepted]))
    major_px = min(item[1] for item in accepted)
    quality = 1.0 if len(accepted) == 2 else 0.75

    cos_phi = 1.0
    theta_deg = math.degrees(math.acos(min(1.0, max(-1.0, ratio / cos_phi))))

    clamped = _clamped_to_range(theta_deg)
    if clamped is None:
        return None
    theta_deg, range_penalty = clamped

    sigma_ratio = math.sqrt(
        (_CHORD_SIGMA_PIXELS / major_px) ** 2
        + (1.0 - math.cos(math.radians(SIDE_AZIMUTH_TOLERANCE_DEG))) ** 2
        + RATIO_SIGMA_PERSPECTIVE**2
    )
    sine = abs(math.sin(math.radians(theta_deg)))
    sigma_theta = math.inf if sine <= 0 else math.degrees(sigma_ratio / sine)

    confidence = _confidence_from_sigma(
        WHEEL_CONFIDENCE_CEILING, sigma_theta, quality * range_penalty
    )
    if confidence < MIN_USEFUL_CONFIDENCE:
        return None
    return ElevationEstimate(theta_deg, confidence, "wheel_ellipse")


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

def _azimuth_class(angle: str | None, width: int, height: int) -> tuple[str, bool]:
    """Which set of UNDERSIDE_GEOMETRY constants applies, and whether it was guessed."""
    if angle in ("front", "rear"):
        return "end", False
    if angle in ("front_quarter", "rear_quarter"):
        return "quarter", False
    if angle == "side":
        return "side", False
    if angle is not None:
        logger.debug("Unrecognised shot angle '%s'; inferring the azimuth class", angle)
    if height <= 0:
        return "quarter", True
    return ("end" if width / height < ASPECT_END_MAX else "quarter"), True


def _roof_underside(cutout: Image.Image, angle: str | None) -> ElevationEstimate | None:
    """Elevation from the height of the see-through gap under the car."""
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    bounds = _visible_bounds(alpha)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    height, width = bottom - top, right - left
    if height < UNDERSIDE_MIN_SILHOUETTE_PX or width < UNDERSIDE_MIN_SILHOUETTE_PX:
        return None

    solid = alpha[:, left:right] >= 128
    has, lowest = _column_bottoms(solid)
    if not has.any():
        return None
    contact = float(np.quantile(lowest[has].astype(np.float64), 0.97))
    gap = np.where(has, np.maximum(0.0, contact - lowest), np.nan)

    on_line = has & (gap <= UNDERSIDE_CONTACT_TOLERANCE * height)

    if int(on_line.sum()) > UNDERSIDE_BOTTOM_FLAT_MAX * width:
        return None

    runs = _runs(on_line)
    if len(runs) < 2 or runs[-1][0] - runs[0][1] < UNDERSIDE_MIN_WHEELBASE_RATIO * width:
        return None

    between = np.zeros(width, dtype=bool)
    between[runs[0][1] + 1:runs[-1][0]] = True
    measurable = between & has & (gap > 0)
    if not measurable.any():
        return None
    ratio = float(np.median(gap[measurable])) / height

    azimuth_class, assumed = _azimuth_class(angle, width, height)
    clearance, lever = UNDERSIDE_GEOMETRY[azimuth_class]

    residual = clearance - ratio * REFERENCE_VEHICLE_HEIGHT_M
    theta_deg = math.degrees(math.atan2(residual, lever))

    clamped = _clamped_to_range(theta_deg)
    if clamped is None:
        return None
    theta_deg, range_penalty = clamped

    sigma_theta = math.degrees(
        CLEARANCE_UNCERTAINTY_M * lever / (lever * lever + residual * residual)
    )
    quality = range_penalty * (AZIMUTH_ASSUMED_PENALTY if assumed else 1.0)

    confidence = _confidence_from_sigma(UNDERSIDE_CONFIDENCE_CEILING, sigma_theta, quality)
    if confidence < MIN_USEFUL_CONFIDENCE:
        return None
    return ElevationEstimate(theta_deg, confidence, "roof_underside")


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True stretches of a boolean array, as inclusive (start, end)."""
    if not flags.any():
        return []
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(edges[i]), int(edges[i + 1]) - 1) for i in range(0, edges.size, 2)]


# ── Rung 3: the shot angle ─────────────────────────────────────────────────────

def _shot_angle(angle: str | None) -> ElevationEstimate | None:
    """A population prior over how dealers actually shoot, once both measurements have
    declined. Nothing is read from the pixels.
    """
    if angle is None:
        return None
    theta_deg = ANGLE_ELEVATION_PRIOR_DEG.get(angle)
    if theta_deg is None:
        logger.debug("No elevation prior for shot angle '%s'; assuming standing", angle)
        return None
    confidence = (
        ANGLE_PRIOR_CONFIDENCE_NAMED
        if angle in _PLAN_NAMED_ANGLES
        else ANGLE_PRIOR_CONFIDENCE_OTHER
    )
    return ElevationEstimate(theta_deg, confidence, "shot_angle")


# ── Entry point ────────────────────────────────────────────────────────────────

def estimate_elevation(cutout: Image.Image, angle: str | None = None) -> ElevationEstimate:
    """Estimate the camera elevation of the photograph this cutout came from."""
    for rung in (_wheel_ellipse, _roof_underside):
        try:
            estimate = rung(cutout, angle)
        except Exception:  # noqa: BLE001 - see the docstring: a rung may never fail a job
            logger.debug("Elevation rung %s failed; handing on", rung.__name__, exc_info=True)
            continue
        if estimate is not None:
            return estimate

    estimate = _shot_angle(angle)
    if estimate is not None:
        return estimate

    return ElevationEstimate(STANDING_ELEVATION_DEG, ASSUMED_CONFIDENCE, "assumed")

