"""Measuring a dealership's own backdrop, so a vehicle can be stood in it correctly."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("autopivot.backdrop_analysis")


HORIZON_METHODS: tuple[str, ...] = ("vanishing_point", "floor_junction", "assumed")

ASSUMED_HORIZON_Y_RATIO = 0.5

ASSUMED_FLOOR_TOP_Y_RATIO = 0.84

MIN_SEGMENT_LENGTH_RATIO = 0.04

MIN_SEGMENT_SLOPE_DEG = 2.0
MAX_SEGMENT_SLOPE_DEG = 75.0

MAX_SEGMENTS = 120

MAX_INTERSECTION_SPREAD = 1.5

FLOOR_EDGE_MIN_STRENGTH = 0.30

FLOOR_MIN_TONAL_STEP = 4.0

VOTE_BIN_RATIO = 0.005

FULL_FRAME_WIDTH_MM = 36.0

_EXIF_FOCAL_LENGTH_35MM = 41989
_EXIF_FOCAL_LENGTH = 37386


@dataclass(frozen=True)
class BackdropGeometry:
    """What one backdrop photograph says about the room it was taken in."""

    horizon_y_ratio: float
    horizon_confidence: float
    horizon_method: str

    floor_top_y_ratio: float
    floor_confidence: float

    focal_length_35mm: float | None

    camera_elevation_deg: float | None


# ── Line geometry ──────────────────────────────────────────────────────────────

def _line_segments(gray: np.ndarray) -> np.ndarray:
    """Every straight edge in the image, as (x1, y1, x2, y2) rows."""
    try:
        detector = cv2.createLineSegmentDetector()
        found = detector.detect(gray)[0]
        if found is not None and len(found):
            return found.reshape(-1, 4)
    except cv2.error as exc:
        logger.debug("Line segment detector unavailable, using Hough instead: %s", exc)

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    minimum = max(20, round(math.hypot(*gray.shape[::-1]) * MIN_SEGMENT_LENGTH_RATIO))
    found = cv2.HoughLinesP(
        edges, 1, np.pi / 360, threshold=60, minLineLength=minimum, maxLineGap=8
    )
    if found is None:
        return np.empty((0, 4), dtype=np.float32)
    return found.reshape(-1, 4).astype(np.float32)


def _receding_segments(segments: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Keep the segments that recede from the camera, longest first."""
    if not len(segments):
        return np.empty((0, 5), dtype=np.float64)

    width, height = size
    x1, y1, x2, y2 = (segments[:, i].astype(np.float64) for i in range(4))
    dx, dy = x2 - x1, y2 - y1
    lengths = np.hypot(dx, dy)

    long_enough = lengths >= math.hypot(width, height) * MIN_SEGMENT_LENGTH_RATIO
    slope_deg = np.degrees(np.arctan2(np.abs(dy), np.maximum(np.abs(dx), 1e-9)))
    receding = (slope_deg >= MIN_SEGMENT_SLOPE_DEG) & (slope_deg <= MAX_SEGMENT_SLOPE_DEG)

    kept = segments[long_enough & receding]
    kept_lengths = lengths[long_enough & receding]
    if not len(kept):
        return np.empty((0, 5), dtype=np.float64)

    order = np.argsort(-kept_lengths)[:MAX_SEGMENTS]
    return np.column_stack([kept[order].astype(np.float64), kept_lengths[order]])


def _intersection_rows(segments: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The y of every pairwise intersection, and how much each vote is worth."""
    count = len(segments)
    if count < 2:
        return np.empty(0), np.empty(0)

    i, j = np.triu_indices(count, k=1)
    x1, y1, x2, y2 = (segments[:, k] for k in range(4))
    lengths = segments[:, 4]

    a = y2 - y1
    b = x1 - x2
    c = a * x1 + b * y1

    determinant = a[i] * b[j] - a[j] * b[i]
    crossing = np.abs(determinant) > 1e-6
    if not crossing.any():
        return np.empty(0), np.empty(0)

    i, j, determinant = i[crossing], j[crossing], determinant[crossing]
    y = (a[i] * c[j] - a[j] * c[i]) / determinant
    weight = np.minimum(lengths[i], lengths[j])
    return y, weight


def _vanishing_row(segments: np.ndarray, height: int) -> tuple[float, float] | None:
    """Where the receding lines agree they meet, and how strongly they agree."""
    y, weight = _intersection_rows(segments)
    if not len(y):
        return None

    inside = np.abs(y - height / 2) <= height * MAX_INTERSECTION_SPREAD
    y, weight = y[inside], weight[inside]
    if not len(y):
        return None

    bin_height = max(1.0, height * VOTE_BIN_RATIO)
    lowest = y.min()
    bins = np.floor((y - lowest) / bin_height).astype(np.int64)
    totals = np.bincount(bins, weights=weight)
    peak = int(np.argmax(totals))

    band = (bins >= peak - 1) & (bins <= peak + 1)
    band_weight = weight[band].sum()
    if band_weight <= 0:
        return None

    row = float((y[band] * weight[band]).sum() / band_weight)
    confidence = float(band_weight / weight.sum())
    return row, confidence


# ── Floor ──────────────────────────────────────────────────────────────────────

def _floor_junction(gray: np.ndarray, horizon_row: float | None) -> tuple[float, float] | None:
    """The row where the back wall meets the floor."""
    height, width = gray.shape
    blurred = cv2.GaussianBlur(gray, (0, 0), max(1.0, height * 0.004))
    gradient = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3))

    middle = gradient[:, round(width * 0.2):round(width * 0.8)]
    rows = middle.mean(axis=1)

    first = round(horizon_row) if horizon_row is not None else round(height * 0.4)
    first = max(1, min(height - 2, first))
    searchable = rows[first:height - 1]
    if not len(searchable) or not np.any(searchable > 0):
        return None

    span = max(2, round(height * 0.02))
    peak = float(searchable.max())
    if peak <= 0:
        return None
    typical = float(np.median(searchable))

    strong = np.flatnonzero(searchable >= max(FLOOR_EDGE_MIN_STRENGTH * peak, typical * 2.0))
    if not strong.size:
        return None

    for offset in strong[::-1]:
        row = first + int(offset)
        above = gray[max(0, row - span * 3):max(0, row - span), :]
        below = gray[min(height - 1, row + span):min(height, row + span * 3), :]
        if not above.size or not below.size:
            continue
        if abs(float(above.mean()) - float(below.mean())) < FLOOR_MIN_TONAL_STEP:
            continue

        strength = float(searchable[offset])
        confidence = float(np.clip((strength - typical) / strength, 0.0, 1.0))
        return float(row), confidence

    return None


# ── Camera ─────────────────────────────────────────────────────────────────────

def _focal_length_35mm(image: Image.Image) -> float | None:
    """The 35 mm equivalent focal length the camera recorded, if it recorded one."""
    try:
        exif = image.getexif()
    except (AttributeError, OSError):
        return None
    if not exif:
        return None

    value = exif.get(_EXIF_FOCAL_LENGTH_35MM)
    if value in (None, 0):
        return None
    try:
        focal = float(value)
    except (TypeError, ValueError):
        return None
    return focal if 8.0 <= focal <= 200.0 else None


def _camera_elevation_deg(
    horizon_row: float, focal_35mm: float | None, size: tuple[int, int]
) -> float | None:
    """How far above the horizontal the camera looked, from where the horizon fell."""
    if focal_35mm is None:
        return None
    width, height = size
    focal_px = focal_35mm * width / FULL_FRAME_WIDTH_MM
    return float(math.degrees(math.atan2(height / 2 - horizon_row, focal_px)))


# ── Entry point ────────────────────────────────────────────────────────────────

def analyse(image: Image.Image) -> BackdropGeometry:
    """Measure a backdrop. Never raises, never returns None."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)

    horizon_row: float | None = None
    horizon_confidence = 0.0
    horizon_method = "assumed"

    vanishing = _vanishing_row(_receding_segments(_line_segments(gray), (width, height)), height)
    if vanishing is not None:
        horizon_row, horizon_confidence = vanishing
        horizon_method = "vanishing_point"

    junction = _floor_junction(gray, horizon_row)

    if horizon_row is None and junction is not None:
        junction_row, junction_confidence = junction
        horizon_row = junction_row
        horizon_confidence = junction_confidence * 0.5
        horizon_method = "floor_junction"

    if horizon_row is None:
        horizon_row = height * ASSUMED_HORIZON_Y_RATIO

    floor_row, floor_confidence = (
        junction if junction is not None else (height * ASSUMED_FLOOR_TOP_Y_RATIO, 0.0)
    )

    geometry = BackdropGeometry(
        horizon_y_ratio=float(np.clip(horizon_row / height, 0.0, 1.0)),
        horizon_confidence=float(np.clip(horizon_confidence, 0.0, 1.0)),
        horizon_method=horizon_method,
        floor_top_y_ratio=float(np.clip(floor_row / height, 0.0, 1.0)),
        floor_confidence=float(np.clip(floor_confidence, 0.0, 1.0)),
        focal_length_35mm=_focal_length_35mm(image),
        camera_elevation_deg=None,
    )

    elevation = _camera_elevation_deg(horizon_row, geometry.focal_length_35mm, (width, height))
    if elevation is None:
        return geometry
    return BackdropGeometry(
        horizon_y_ratio=geometry.horizon_y_ratio,
        horizon_confidence=geometry.horizon_confidence,
        horizon_method=geometry.horizon_method,
        floor_top_y_ratio=geometry.floor_top_y_ratio,
        floor_confidence=geometry.floor_confidence,
        focal_length_35mm=geometry.focal_length_35mm,
        camera_elevation_deg=elevation,
    )

