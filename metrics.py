"""Numbers for judging whether a realism change actually worked."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

EDGE_SOLID_ALPHA = 128

EDGE_BAND_RATIO = 0.004


@dataclass(frozen=True)
class EdgeQuality:
    """How much of a cut-out's boundary is genuinely fractional rather than cut."""

    fractional: int
    silhouette: int
    ratio: float


def _alpha_of(image: Image.Image) -> np.ndarray:
    """The alpha to measure, as uint8."""
    bands = image.getbands()
    if "A" in bands:
        return np.array(image.getchannel("A"), dtype=np.uint8)
    if len(bands) == 1:
        return np.array(image.convert("L"), dtype=np.uint8)
    return np.full((image.height, image.width), 255, dtype=np.uint8)


def edge_quality(image: Image.Image) -> EdgeQuality:
    """Count the alpha values strictly between 0 and 255 along the silhouette."""
    alpha = _alpha_of(image)
    solid = np.where(alpha >= EDGE_SOLID_ALPHA, 255, 0).astype(np.uint8)

    rows, columns = np.nonzero(solid)
    if rows.size == 0:
        return EdgeQuality(0, 0, 0.0)

    diagonal = float(np.hypot(
        columns.max() - columns.min() + 1,
        rows.max() - rows.min() + 1,
    ))
    radius = max(1, round(EDGE_BAND_RATIO * diagonal))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
    )

    in_band = cv2.subtract(cv2.dilate(solid, kernel), cv2.erode(solid, kernel)) > 0
    silhouette = int(np.count_nonzero(in_band))
    if silhouette == 0:
        return EdgeQuality(0, 0, 0.0)

    fractional = int(np.count_nonzero(in_band & (alpha > 0) & (alpha < 255)))
    return EdgeQuality(fractional, silhouette, fractional / silhouette)


def horizon_offset(
    vehicle_horizon_ratio: float,
    backdrop_horizon_ratio: float,
    canvas_height: int,
) -> float:
    """How far the vehicle's horizon misses the backdrop's, in canvas pixels."""
    return (vehicle_horizon_ratio - backdrop_horizon_ratio) * canvas_height


def size_spread(heights: Sequence[float]) -> float:
    """The largest rendered vehicle height in a gallery over the smallest."""
    if not heights:
        raise ValueError("size spread needs at least one rendered height")
    smallest, largest = min(heights), max(heights)
    if smallest <= 0:
        raise ValueError(
            f"a rendered vehicle height of {smallest} means nothing was rendered"
        )
    return float(largest) / float(smallest)

