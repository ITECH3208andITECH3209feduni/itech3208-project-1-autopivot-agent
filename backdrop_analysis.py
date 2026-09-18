"""Measuring a dealership's own backdrop, so a vehicle can be stood in it correctly.

A dealer uploads a photograph of their showroom, their workshop or their forecourt
and expects a car to appear in it standing on the floor. Until now the compositor
assumed every such backdrop had its ground line 84% of the way down the canvas,
which is right for the two studio scenes and a guess everywhere else: a backdrop
whose floor meets the wall higher than that leaves the vehicle sunk into the
concrete, and one whose floor sits lower leaves it hovering. That is the second
item on the handover's list of known gaps, and it is also the half of Phase 1
that `elevation.py` cannot supply — that module measures where the CAMERA was for
one photograph, and this one measures where the FLOOR is in one backdrop. The two
meet in the compositor.

Everything here is classical geometry over cv2, numpy and PIL. That is not a
stylistic preference: backdrops are uploaded through `api/routes_backdrops.py`,
which lives in the light half of the application and imports no machine learning
at all. An analyser that reached for a model would mean a dealership could not
upload a backdrop without a GPU, which would break the split the whole system is
arranged around.

Nothing here is allowed to be confidently wrong. Every measurement carries a
confidence and the name of the method that produced it, and a scene that offers
no geometry at all — a seamless white cyclorama has no lines in it to converge —
falls back and says that it fell back, so a dealer can be shown a guess as a
guess and correct it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("autopivot.backdrop_analysis")


# How the horizon was arrived at, strongest first. Written to the backdrop record
# so a dealer can be told which, and so a low-confidence guess is never mistaken
# for a measurement.
HORIZON_METHODS: tuple[str, ...] = ("vanishing_point", "floor_junction", "assumed")

# Where the horizon is assumed to be when a scene yields nothing. A photograph
# taken by a person standing and holding a phone level puts the horizon through
# the middle of the frame, and that is the least-wrong assumption available;
# it is recorded as "assumed" precisely so nothing downstream trusts it.
ASSUMED_HORIZON_Y_RATIO = 0.5

# The ground line that shipped before this module existed. Kept as the final
# fallback so a backdrop the analyser cannot read composites exactly as it did
# before, rather than moving under a dealer who was happy with it.
ASSUMED_FLOOR_TOP_Y_RATIO = 0.84

# A segment must be at least this fraction of the image diagonal to vote. Short
# segments are mostly texture — floor grain, wall speckle, the edge of a
# reflection — and they outnumber the real architectural lines by a wide enough
# margin to drown them out entirely if allowed in.
MIN_SEGMENT_LENGTH_RATIO = 0.04

# Only segments sloping within this band recede from the camera usefully. A line
# closer to horizontal than the lower bound is parallel to the image plane and
# meets its twin at infinity, contributing nothing; one steeper than the upper
# bound is effectively a vertical — a door frame, a wall corner, a pillar — and
# its vanishing point is the vertical one, which is not the horizon.
MIN_SEGMENT_SLOPE_DEG = 2.0
MAX_SEGMENT_SLOPE_DEG = 75.0

# Pairwise intersection is quadratic, so the segment list is capped. Sorted by
# length first, which keeps the architecture and discards the texture.
MAX_SEGMENTS = 120

# An intersection this far outside the frame is not a horizon anyone is looking
# at, and including them lets a pair of nearly-parallel lines throw a vote
# thousands of pixels away that no amount of averaging recovers from.
MAX_INTERSECTION_SPREAD = 1.5

# How strong a horizontal edge must be, against the strongest one below the
# horizon, to be considered as the floor at all. Low enough that a real junction
# between two similarly-toned surfaces still qualifies — a pale floor meeting a
# pale wall is a weak edge and still a floor — and high enough that the search
# does not walk down into the floor's own texture and stop at a scuff mark.
FLOOR_EDGE_MIN_STRENGTH = 0.30

# How far the surfaces either side of a candidate must differ in tone, in 8-bit
# levels, before it counts as a boundary between two of them rather than a
# marking on one.
FLOOR_MIN_TONAL_STEP = 4.0

# The vote histogram's resolution, as a fraction of image height. Fine enough to
# locate a horizon usefully, coarse enough that the votes of one real vanishing
# point land in the same bin rather than smearing across ten.
VOTE_BIN_RATIO = 0.005

# 35 mm film is 36 mm wide, which is what turns an EXIF focal length in 35 mm
# equivalent terms into a focal length in pixels for an image of known width.
FULL_FRAME_WIDTH_MM = 36.0

# EXIF tag numbers. Pillow returns a plain integer-keyed mapping, and naming
# these is clearer than three magic numbers at the call site.
_EXIF_FOCAL_LENGTH_35MM = 41989
_EXIF_FOCAL_LENGTH = 37386


@dataclass(frozen=True)
class BackdropGeometry:
    """
    What one backdrop photograph says about the room it was taken in.

    Ratios run down the canvas: 0.0 is the top edge, 1.0 the bottom. They are
    ratios rather than pixels because a backdrop is rescaled to the output
    canvas before a vehicle is placed in it, and a pixel measured on the upload
    would stop meaning anything the moment it was.
    """

    # Where the camera's own eye level falls in the frame. This is the number
    # Phase 1 aligns a photograph's estimated horizon against.
    horizon_y_ratio: float
    horizon_confidence: float
    horizon_method: str

    # Where the floor begins — the wall-floor junction, the furthest point a
    # vehicle could stand. It is deliberately not where the vehicle is put:
    # standing a car exactly on the junction presses it against the back wall.
    # Choosing a spot on the floor is the compositor's decision, not a
    # measurement, and it is made there.
    floor_top_y_ratio: float
    floor_confidence: float

    # Read from EXIF when the dealer's phone recorded it. Its value is that it
    # makes the camera elevation below a measurement rather than an assumption.
    focal_length_35mm: float | None

    # How far above the horizontal the camera sat, positive when it was above.
    # None when there is no focal length to derive it from — an angle cannot be
    # recovered from a horizon position alone, and inventing a sensor size to
    # fill the gap would produce a number that looks measured and is not.
    camera_elevation_deg: float | None


# ── Line geometry ──────────────────────────────────────────────────────────────

def _line_segments(gray: np.ndarray) -> np.ndarray:
    """
    Every straight edge in the image, as (x1, y1, x2, y2) rows.

    The line segment detector is tried first because it finds edges at their
    true extent rather than at whatever the accumulator threshold happens to
    admit. It is absent or disabled in some OpenCV builds — it was removed
    outright for several releases over a patent — so a failure here is expected
    rather than exceptional, and the probabilistic Hough transform stands in.
    """
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
    """
    Keep the segments that recede from the camera, longest first.

    Returned as (x1, y1, x2, y2, length) rows so the length is carried rather
    than recomputed at every pairing — the pairing is quadratic and this is the
    inner loop.
    """
    if not len(segments):
        return np.empty((0, 5), dtype=np.float64)

    width, height = size
    x1, y1, x2, y2 = (segments[:, i].astype(np.float64) for i in range(4))
    dx, dy = x2 - x1, y2 - y1
    lengths = np.hypot(dx, dy)

    long_enough = lengths >= math.hypot(width, height) * MIN_SEGMENT_LENGTH_RATIO
    # A vertical segment has no gradient to speak of, so the angle is taken from
    # the components directly rather than through a division that would divide
    # by zero on exactly the segments being excluded.
    slope_deg = np.degrees(np.arctan2(np.abs(dy), np.maximum(np.abs(dx), 1e-9)))
    receding = (slope_deg >= MIN_SEGMENT_SLOPE_DEG) & (slope_deg <= MAX_SEGMENT_SLOPE_DEG)

    kept = segments[long_enough & receding]
    kept_lengths = lengths[long_enough & receding]
    if not len(kept):
        return np.empty((0, 5), dtype=np.float64)

    order = np.argsort(-kept_lengths)[:MAX_SEGMENTS]
    return np.column_stack([kept[order].astype(np.float64), kept_lengths[order]])


def _intersection_rows(segments: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    The y of every pairwise intersection, and how much each vote is worth.

    A vote is worth the shorter of the two segments that cast it: a long line
    crossing a short one is only as trustworthy as the short one, and weighting
    by the longer would let a single architectural edge dominate the histogram
    by pairing with every scrap of texture that survived the length filter.
    """
    count = len(segments)
    if count < 2:
        return np.empty(0), np.empty(0)

    i, j = np.triu_indices(count, k=1)
    x1, y1, x2, y2 = (segments[:, k] for k in range(4))
    lengths = segments[:, 4]

    # Each segment as the line a*x + b*y = c through its endpoints.
    a = y2 - y1
    b = x1 - x2
    c = a * x1 + b * y1

    determinant = a[i] * b[j] - a[j] * b[i]
    # Parallel lines meet at infinity, which is not a horizon. Excluded rather
    # than clamped: a near-zero determinant produces an intersection millions of
    # pixels away and one of those in the histogram is enough to shift a mean.
    crossing = np.abs(determinant) > 1e-6
    if not crossing.any():
        return np.empty(0), np.empty(0)

    i, j, determinant = i[crossing], j[crossing], determinant[crossing]
    y = (a[i] * c[j] - a[j] * c[i]) / determinant
    weight = np.minimum(lengths[i], lengths[j])
    return y, weight


def _vanishing_row(segments: np.ndarray, height: int) -> tuple[float, float] | None:
    """
    Where the receding lines agree they meet, and how strongly they agree.

    Returns the row and a confidence, or None when there is no agreement worth
    reporting. The confidence is the share of the total vote that landed in the
    winning band, which is the honest quantity: a room whose floor, ceiling and
    skirting all converge on one point scores high, and a scene where three
    unrelated diagonals happen to cross scores low even though a peak exists.
    """
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

    # The winning bin and its immediate neighbours, so a vanishing point sitting
    # on a bin boundary is not split in half and reported as two weak peaks.
    band = (bins >= peak - 1) & (bins <= peak + 1)
    band_weight = weight[band].sum()
    if band_weight <= 0:
        return None

    row = float((y[band] * weight[band]).sum() / band_weight)
    confidence = float(band_weight / weight.sum())
    return row, confidence


# ── Floor ──────────────────────────────────────────────────────────────────────

def _floor_junction(gray: np.ndarray, horizon_row: float | None) -> tuple[float, float] | None:
    """
    The row where the back wall meets the floor.

    Found as the strongest horizontal edge in the lower part of the frame,
    scored across the middle of the image only. The outer thirds are where the
    side walls are, and their junctions are diagonals that smear a row-wise
    score across everything they cross; the middle is where the junction is
    actually horizontal.

    A wall and a floor also differ in tone, so the edge is required to separate
    two regions of genuinely different brightness. Without that a strong
    reflection or a painted stripe scores as well as the junction does.
    """
    height, width = gray.shape
    blurred = cv2.GaussianBlur(gray, (0, 0), max(1.0, height * 0.004))
    gradient = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3))

    middle = gradient[:, round(width * 0.2):round(width * 0.8)]
    rows = middle.mean(axis=1)

    # Only below the horizon: the floor cannot be above the camera's eye level,
    # and the strongest horizontal edge in a showroom is often the ceiling.
    first = round(horizon_row) if horizon_row is not None else round(height * 0.4)
    first = max(1, min(height - 2, first))
    searchable = rows[first:height - 1]
    if not len(searchable) or not np.any(searchable > 0):
        return None

    # THE LOWEST STRONG EDGE, NOT THE STRONGEST, and the difference is the whole
    # of this function's accuracy on a real photograph.
    #
    # A dealer's showroom is full of horizontal architecture above its floor: a
    # dark band around the walls, a skirting, a lighting cove, the shadow line
    # under a counter. Any of those can out-gradient the wall-floor junction,
    # and taking the strongest edge picked a black wall stripe at 0.49 in a real
    # backdrop whose floor began at 0.55 — with a confidence of 0.99, because
    # the stripe genuinely is the strongest edge in the frame. The vehicle then
    # stood 130 pixels above the floor and visibly floated.
    #
    # What separates the floor from all of that is not strength but position: it
    # is the last horizontal boundary before the bottom of the frame, because
    # everything below it is the surface the car will stand on.
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
        # Both bands are sampled a clear span away from the edge itself. A
        # painted stripe or a skirting board has a different tone for its own
        # thickness and then returns to the surface it was drawn on, so reading
        # the rows immediately either side of it finds a step that is not a
        # change of surface at all.
        above = gray[max(0, row - span * 3):max(0, row - span), :]
        below = gray[min(height - 1, row + span):min(height, row + span * 3), :]
        if not above.size or not below.size:
            continue
        if abs(float(above.mean()) - float(below.mean())) < FLOOR_MIN_TONAL_STEP:
            continue

        # How far this edge stands above the ordinary gradient of the search
        # band. A real junction is a spike; a gently shaded floor is a plateau
        # that happens to have a maximum somewhere.
        strength = float(searchable[offset])
        confidence = float(np.clip((strength - typical) / strength, 0.0, 1.0))
        return float(row), confidence

    return None


# ── Camera ─────────────────────────────────────────────────────────────────────

def _focal_length_35mm(image: Image.Image) -> float | None:
    """
    The 35 mm equivalent focal length the camera recorded, if it recorded one.

    A phone writes this into EXIF and a render does not, so this is the one
    signal here that separates a photograph of a real showroom from a
    visualisation of one. Only the 35 mm equivalent is used: a bare focal length
    in millimetres means nothing without the sensor size, which phones report
    inconsistently when they report it at all.
    """
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
    # A 35 mm equivalent outside this range is a corrupt tag rather than an
    # exotic lens, and one bad value would put the elevation wildly out.
    return focal if 8.0 <= focal <= 200.0 else None


def _camera_elevation_deg(
    horizon_row: float, focal_35mm: float | None, size: tuple[int, int]
) -> float | None:
    """
    How far above the horizontal the camera looked, from where the horizon fell.

    A level camera puts the horizon through the centre of the frame. Tilting the
    camera down to take in the floor lifts the horizon up the image, so a
    horizon above centre means the camera was above what it was looking at,
    which is the same sign convention `elevation.py` uses for a photograph.
    """
    if focal_35mm is None:
        return None
    width, height = size
    focal_px = focal_35mm * width / FULL_FRAME_WIDTH_MM
    return float(math.degrees(math.atan2(height / 2 - horizon_row, focal_px)))


# ── Entry point ────────────────────────────────────────────────────────────────

def analyse(image: Image.Image) -> BackdropGeometry:
    """
    Measure a backdrop. Never raises, never returns None.

    A backdrop that yields nothing composites exactly as it did before this
    module existed — the assumed values are the constants that were hard-coded
    into the compositor — and says so through its methods and confidences, so
    the difference between a measured backdrop and an unreadable one is visible
    rather than silently absorbed.
    """
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
        # No lines converged, but a floor was found. The horizon cannot be below
        # the floor it stands on, and in a room photographed from standing
        # height the junction sits a little below eye level, so the junction is
        # the better guess of the two available — but only just, and the
        # confidence says so.
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
