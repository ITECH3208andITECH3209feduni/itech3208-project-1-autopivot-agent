"""Estimating the camera elevation of a source photograph, from the cutout alone.

The studio scene is a raised turntable, so the room behind a vehicle is the same
in every photograph and one backdrop is already correct for azimuth. What does
not match is camera height: a dealer crouches for the front three-quarter,
stands for the side and holds the phone overhead for the rear, and each of those
has a different horizon. This module measures that, with no new model, from the
detection and alpha the pipeline already produces.

`estimate_elevation` is a four-rung cascade. Each rung above the last is allowed
to decline, and the last one assumes standing eye level and says so, so a job
records a low-confidence guess rather than a wrong certainty. At most one rung
ever measures anything for a given photograph: the wheel ellipse for a side-on
shot, the underside gap for a head-on or tail-on one below about sixteen degrees,
and for everything else — both quarter angles included, for a reason set out at
the contact-line test in `_roof_underside` — a population prior over how dealers
shoot.

DEPARTURE FROM REALISM_PLAN.md, PHASE 1 — read this before concluding the code
is a mistake.

REALISM_PLAN.md says a wheel's "minor-over-major axis ratio is approximately the
sine of the viewing elevation: head-on at ground level, a wheel is a line; from
directly above, a circle." That sentence is wrong, and wrong in the direction
that matters, so this module implements the cosine relationship instead.

The plan conflated two different circles. A circle lying in a HORIZONTAL plane —
the turntable, the platform ellipse `compositing._platform_mask` draws, a manhole
cover — has a vertical normal, so its axis ratio really is |sin(elevation)|,
independent of azimuth. That is the standard turntable intuition and it is
correct; nothing in compositing.py is affected. A car's WHEEL is not that circle.
Its axis points sideways out of the car, so the wheel disc lies in a VERTICAL
plane parallel to the flank and its normal is horizontal, not vertical.

For a circle with unit normal n viewed along unit direction v under orthographic
projection, the major axis is the true diameter and

    minor / major = |n . v|

With theta the camera elevation and phi the azimuth measured away from side-on
(phi = 0 is a full side profile, phi = 90 deg is head-on or tail-on), a wheel
therefore gives

    minor / major = |cos(theta) * cos(phi)|

The plan's first example survives by coincidence — at ground level both formulae
give zero, though the correct one gives it because of the AZIMUTH, cos(90 deg),
not the elevation. Its second example is simply false: from a helicopter directly
over a car the tyres are seen edge-on as thin strips, and projecting a unit
circle with a horizontal normal at theta = 90 deg measures a ratio of 0.0003,
where sin(theta) predicts 1.0.

The reason this had to be a documented departure rather than a faithful
implementation is that the wrong formula hides its own sensitivity problem.
sin(theta) has derivative cos(theta) ~ 1 near zero, so it implies the measurement
is MOST sensitive exactly in the 3-20 deg range dealer photographs occupy. The
true relation, cos(theta), has derivative -sin(theta) ~ 0 there, so it is LEAST
sensitive precisely there. Over the plan's own three camera heights the plan's
formula predicts axis ratios of 0.080 -> 0.194 -> 0.300, trivially separable;
the true formula gives 0.997 -> 0.981 -> 0.954, barely separable. Same
photographs, opposite engineering conclusions. Implementing the plan as written
would have produced a module that looked precise in the regime where it is in
fact nearly blind.

The recommended edit to REALISM_PLAN.md — not made here, this module writes
nothing — is to replace that sentence with the relationship above and to note
that it is the azimuth, not the elevation, that drives a wheel to a line head-on.

WHAT THAT COSTS, AND WHY NO RUNG MAY SOUND CONFIDENT.

Because theta = arccos(ratio), d(theta)/d(ratio) = 1 / sin(theta), and sin(theta)
is small exactly where the answer is wanted: a 1% error in the ratio moves the
answer by 7.2 deg at 4.6 deg elevation and by 1.9 deg at 17.4 deg. A one-percent
measurement error therefore costs between a quarter and the whole of the range
being resolved. Three error sources are each large enough to swamp the signal on
their own: the azimuth (10 deg of residual error inside a 'side' label turns a
true 11.16 deg into 14.94 deg), wheel-arch occlusion (which is why rung 1 scans
chords instead of calling cv2.fitEllipse), and the unknown shooting distance (the
same standing photographer is 21.5 deg at 3 m and 8.4 deg at 8 m, and a monocular
cutout cannot recover which).

Three consequences are built into the code rather than left as prose:

  * No rung may return a high confidence. The ceilings 0.55 / 0.35 / 0.20 / 0.10
    come from the analysis above and are not decoration.
  * Confidence is computed as CONFIDENCE_REFERENCE_SIGMA_DEG / sigma_theta with
    sigma_theta propagated through the inverse, so it collapses on its own at low
    elevation. A flat per-rung confidence would be a lie precisely where this
    module is blindest.
  * The honest claim is ordinal, not cardinal: this can usually tell a genuinely
    high camera from a genuinely low one, and cannot reliably tell crouching from
    standing. Phase 1 should use the output to choose among Suraj Purella's three
    backdrop variants with a confidence-weighted shift, not as a metric horizon
    offset in pixels.

Stage 0's evidence harness should record the raw axis ratio and the raw underside
gap alongside the degrees, because reporting only the degrees discards the
measurement and keeps the inference, and it is the measurement that lets these
constants be calibrated against real photographs later.

Only cv2, numpy and PIL are imported, the same three compositing.py holds itself
to, which is what lets the tests beside this run on a machine with no GPU and no
torch.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("autopivot.elevation")

# Which rung of the cascade produced a number. Written to the job beside the
# degrees, so a reader can tell a measurement from a population prior.
ELEVATION_METHODS = ("wheel_ellipse", "roof_underside", "shot_angle", "assumed")

# The two rungs that read the photograph. The other two do not: 'shot_angle' is a
# population prior over how dealers are known to shoot and 'assumed' is standing
# eye level, and both return the same number for every photograph carrying the
# same label, however that particular car was actually photographed.
#
# The distinction matters more than the confidence attached to it, and anything
# acting on an estimate should test this rather than a threshold. A prior sits
# above the confidence floor by design — it does carry one real bit, that a rear
# shot is more often taken high than a front-quarter — but a bit about dealers in
# general is not a measurement of this photograph, and moving a dealer's backdrop
# by it would be dressing an assumption up as an observation.
MEASURED_METHODS = ("wheel_ellipse", "roof_underside")


# ── The vehicle this module assumes ────────────────────────────────────────────

# A 205/55R16, the commonest fitment across the ANZ used-car fleet: a 406.4 mm
# rim plus two 112.75 mm sidewalls is 631.9 mm. It sets the wheel-size gates and,
# halved, the height the elevation angle is measured to.
WHEEL_DIAMETER_M = 0.632

# THE REFERENCE FOR theta, and it cannot be left implicit: "elevation above the
# horizontal through the vehicle" is ambiguous by several degrees. theta is the
# angle at the camera between the horizontal and the ray to a point this high
# above the ground the vehicle stands on. The wheel centre is the one point on a
# car whose height is fixed by the tyre rather than by the body, and it is the ray
# whose foreshortening rung 1 literally measures, so defining theta to it keeps
# all four rungs answering the same question; measuring to the body centre
# instead, about 0.72 m, would shift every number by a third of the useful range.
#
# Conversion for downstream use: camera_height = 0.316 + distance * tan(theta).
WHEEL_CENTRE_HEIGHT_M = WHEEL_DIAMETER_M / 2.0

# The same sedan compositing.REFERENCE_VEHICLE_ASPECT was derived from. Reusing
# its dimensions rather than picking a fresh reference car is what stops the two
# modules disagreeing about what a typical vehicle is. Only the height is read
# below, but the length and the width are what ASPECT_END_MAX's 1.26-against-3.24
# cut comes out of, and tests/test_elevation.py renders its synthetic car from
# all three, so a change here moves the tests' geometry with the module's.
REFERENCE_VEHICLE_LENGTH_M = 4.70
REFERENCE_VEHICLE_WIDTH_M = 1.83
REFERENCE_VEHICLE_HEIGHT_M = 1.45

# At 6 m a 4.70 m car subtends 42.6 deg horizontally, which sits comfortably
# inside a phone main camera's roughly 67 deg field with room for the lot around
# it; at 4 m it subtends 61 deg and touches both frame edges. This is the only
# place the module assumes a distance, and it is assumed because a monocular
# cutout cannot recover one.
TYPICAL_SHOOTING_DISTANCE_M = 6.0

# The three heights REALISM_PLAN.md commissions from Suraj Purella for the
# backdrop variants. The module's own reference angles are derived from these
# rather than typed in, so that a variant re-rendered at a different height moves
# the estimator's targets with it instead of leaving the two silently disagreeing.
CROUCHING_CAMERA_HEIGHT_M = 0.80
STANDING_CAMERA_HEIGHT_M = 1.50
RAISED_CAMERA_HEIGHT_M = 2.20


def _elevation_for_camera_height(camera_height_m: float) -> float:
    """The elevation a camera at this height sees the wheel centre at, in degrees."""
    return math.degrees(
        math.atan2(camera_height_m - WHEEL_CENTRE_HEIGHT_M, TYPICAL_SHOOTING_DISTANCE_M)
    )


def camera_height_for_elevation(elevation_deg: float) -> float:
    """
    How high the camera stood, in metres, to see the wheel centre at this angle.

    The inverse of the function above, and public because the compositor needs
    it: a horizon is a height above the ground, not an angle, and turning an
    estimated elevation into one has to use the same reference distance the
    estimate was made against. Deriving it here rather than in the compositor is
    what stops the two modules assuming different geometry and disagreeing about
    where the same photograph's eye level falls.
    """
    return WHEEL_CENTRE_HEIGHT_M + TYPICAL_SHOOTING_DISTANCE_M * math.tan(
        math.radians(elevation_deg)
    )


CROUCHING_ELEVATION_DEG = _elevation_for_camera_height(CROUCHING_CAMERA_HEIGHT_M)  # 4.61
STANDING_ELEVATION_DEG = _elevation_for_camera_height(STANDING_CAMERA_HEIGHT_M)    # 11.16
RAISED_ELEVATION_DEG = _elevation_for_camera_height(RAISED_CAMERA_HEIGHT_M)        # 17.43


# ── The plausible range ────────────────────────────────────────────────────────

# theta = atan((camera_height - 0.316) / distance) over the range a person with a
# phone can produce. A raised phone at 2.4 m from an unusually close 3 m gives
# 32.1 deg, rounded up to 35 for margin; anything above that needs a ladder, a
# first-floor window or a drone, none of which is the dealer-walking-round-a-lot
# case Phase 1 is built for. At the other end a photographer kneeling right down
# with the phone at 0.25 m is BELOW the wheel centre and produces a genuinely
# negative angle, which -5 admits without admitting nonsense.
MIN_ELEVATION_DEG = -5.0
MAX_ELEVATION_DEG = 35.0

# How far past the range a rung's raw answer may fall and still be clamped rather
# than discarded. Small on purpose: a couple of degrees is quantisation, twenty
# is a wrong azimuth. See `_clamped_to_range` for why the far case must reject.
OUT_OF_RANGE_TOLERANCE_DEG = 3.0


# ── Confidence policy ──────────────────────────────────────────────────────────

# The propagated one-sigma uncertainty at which a rung earns its full ceiling.
# Five degrees because the three backdrop variants sit 6.5 and 6.3 deg apart, so
# an estimate better than that can choose between them and one worse cannot.
CONFIDENCE_REFERENCE_SIGMA_DEG = 5.0

# The four ceilings. Nothing reaches 1.0, and the reason belongs here rather than
# in a retrospective: even a perfect elevation ANGLE does not name a camera
# HEIGHT, because the same standing photographer is 16.5 deg at 4 m and 8.4 deg
# at 8 m — and a height is what Phase 1 selects a backdrop variant by.
WHEEL_CONFIDENCE_CEILING = 0.55
UNDERSIDE_CONFIDENCE_CEILING = 0.35
ANGLE_PRIOR_CONFIDENCE_NAMED = 0.20
ANGLE_PRIOR_CONFIDENCE_OTHER = 0.15
ASSUMED_CONFIDENCE = 0.10

# Below this a rung hands on rather than reporting. It corresponds to a
# propagated sigma of about 23 deg — an estimate whose one-sigma band covers the
# whole plausible range, and therefore carries no information. Applying one
# threshold uniformly is what makes rung 2's refusal to run side-on a derived
# consequence of its own arithmetic rather than a special case someone wrote in.
MIN_USEFUL_CONFIDENCE = 0.12

# Applied when the azimuth class was inferred from the silhouette's aspect ratio
# rather than handed to us by the classifier.
AZIMUTH_ASSUMED_PENALTY = 0.6


# ── Rung 1: the wheel ellipse ──────────────────────────────────────────────────

# The bottom fraction of the silhouette searched for tyres. A 0.632 m wheel
# against a 1.45 m car reaches 0.436 of the body height, so 0.55 clears it with
# margin while excluding the two things that otherwise pass a darkness test: a
# dark roof and tinted glass.
WHEEL_SEARCH_BAND = 0.55

# A relative threshold is what survives an underexposed dealer photograph, where
# a fixed cut finds either everything or nothing. The absolute ceiling on top of
# it is what stops a white car's 15th percentile, which is still bright, being
# called rubber. A black car fails this rung by producing one huge component that
# the size gates reject, which is the correct outcome.
TYRE_LIGHTNESS_PERCENTILE = 0.15
TYRE_LIGHTNESS_CEILING = 96  # LAB L, 0-255

# Tyres are neutral. Red paint in shadow is just as dark as a tyre and would
# otherwise be segmented as one; saturation is what separates them.
TYRE_SATURATION_MAX = 64  # HSV S, 0-255

# The wheel's major axis against the silhouette height. Covers 0.60-0.80 m wheels
# on 1.35-1.95 m vehicles (0.31 to 0.59) with a little margin either side. Gating
# on the major axis rather than on area works at every azimuth, because the
# projected major axis is always the true diameter whatever theta and phi are.
WHEEL_MAJOR_MIN_RATIO = 0.25
WHEEL_MAJOR_MAX_RATIO = 0.62

# Measured, not guessed. With a 200 px wheel diameter a 1 px error in the chord
# row reads 11.16 deg as 8.1 deg; at 120 px it reads it as 0 deg; at 60 px the
# ratio exceeds 1 and the measurement is destroyed. A car filling a 3000 px
# photograph gives about a 400 px wheel, so real inputs usually clear this and a
# 1024 px upload usually does not.
WHEEL_MIN_MAJOR_PX = 160

# The widths at which the tyre's unoccluded lower arc is sampled. Four fractions
# medianed rather than one, because a segmentation-derived tyre edge is ragged
# and a single crossing is one bad row away from a 10 deg error.
WHEEL_CHORD_FRACTIONS = (0.70, 0.80, 0.90, 0.95)

# How far two accepted wheels may disagree. Larger than any real difference
# between the front and rear wheel of one car at one azimuth, and far smaller
# than the difference between a wheel and something that is not one.
WHEEL_RATIO_SPREAD_MAX = 0.06

# How close a candidate's lowest row must sit to the contact line, as a fraction
# of silhouette height. A tyre touches the ground; a dark door handle, the shadow
# under a mirror and a black bumper insert do not.
TYRE_CONTACT_TOLERANCE = 0.02

# The assumed spread of true azimuth inside CLIP's 'side' label. Not a gate: it
# is an error term feeding rung 1's confidence, and it is the reason that
# confidence is capped well below certainty. It is one-sided — a real azimuth off
# side-on always lowers the observed ratio and therefore always INFLATES the
# reported elevation, so any correction downstream should know the rung's bias
# points upward.
SIDE_AZIMUTH_TOLERANCE_DEG = 10.0

# The weak-perspective error in the axis ratio at TYPICAL_SHOOTING_DISTANCE_M.
# The wheel's depth extent is 0.632*sin(theta), which at 6 m is 0.85% of the
# distance at 4.6 deg, 2.04% at 11.2 deg and 3.16% at 17.4 deg; the orthographic
# model used to invert the ratio does not account for any of it.
RATIO_SIGMA_PERSPECTIVE = 0.02

# A one-pixel error on the chord row, divided by K(0.9) = 0.564, is 1.77 px of
# semi-minor axis; expressed against the major axis that is 2 * 1.77 / major_px.
# On a 400 px wheel it is 0.009, on a 200 px wheel 0.018.
_CHORD_SIGMA_PIXELS = 3.6


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

# Per azimuth class, as (clearance_m, lever_m). Clearance is the height of the
# lowest body edge visible between the wheels — the rocker panel side-on, the
# front valance end-on. Lever is its horizontal offset from the near contact
# patch, which is what sets how fast the underside gap closes as the camera
# rises, and the lever is the whole story of this rung's applicability: 0.85 m
# end-on makes a 0.05 m clearance error cost 3.3 deg, while 0.105 m side-on makes
# the same error cost 25 deg.
UNDERSIDE_GEOMETRY: dict[str, tuple[float, float]] = {
    "side": (0.16, 0.105),
    "quarter": (0.21, 0.48),
    "end": (0.25, 0.85),
}

# The spread of ground clearance across the ANZ fleet, from a lowered hatchback
# at about 0.11 m to a ute at about 0.24 m. This single constant, propagated
# through rung 2's inverse, derives both the rung's confidence and its refusal to
# run side-on.
CLEARANCE_UNCERTAINTY_M = 0.05

# Visible width over height below which an unlabelled cutout is treated as
# end-on. compositing.py's own derivation puts a head-on car at 1.26 and
# everything else at 3.24-3.48, so the cut sits in a wide empty gap. It
# deliberately does not attempt to separate side from quarter, because nothing in
# the silhouette can.
ASPECT_END_MAX = 2.2

# The share of the silhouette width that may sit on the contact line before the
# bottom counts as flat rather than as two contact patches. A genuine cutout puts
# about 8% of the width on the line side-on and 22% end-on; see `_roof_underside`
# for the two quite different failures a flat bottom means.
UNDERSIDE_BOTTOM_FLAT_MAX = 0.55

# How close to the contact line a column has to sit to count as standing on it.
UNDERSIDE_CONTACT_TOLERANCE = 0.01

# The gap is only about 10% of the silhouette height, so below this there are not
# enough rows to measure it in.
UNDERSIDE_MIN_SILHOUETTE_PX = 64

# The minimum separation between the outermost runs of contact columns before
# they can be called a wheelbase rather than one ragged contact patch.
UNDERSIDE_MIN_WHEELBASE_RATIO = 0.20


# ── Rung 3: the population prior ───────────────────────────────────────────────

# REALISM_PLAN.md's own observation, in its Phase 1 preamble: dealers crouch for
# the front three-quarter, stand for the side and hold the phone overhead for the
# rear. The angles it does not name get standing, which is the population mode.
# The three named values are derived from the commissioned camera heights above
# rather than typed in, so the module's numbers and the backdrop variants cannot
# drift apart.
ANGLE_ELEVATION_PRIOR_DEG: dict[str, float] = {
    "front_quarter": CROUCHING_ELEVATION_DEG,
    "side": STANDING_ELEVATION_DEG,
    "rear": RAISED_ELEVATION_DEG,
    "front": STANDING_ELEVATION_DEG,
    # Not named by the plan; midway between standing and raised, following the
    # plan's own grouping of the rear and rear-quarter shots.
    "rear_quarter": (STANDING_ELEVATION_DEG + RAISED_ELEVATION_DEG) / 2.0,
}

# The angles REALISM_PLAN.md actually names, which are the ones whose prior
# carries a real bit of information rather than the population mode.
_PLAN_NAMED_ANGLES = ("front_quarter", "side", "rear")


@dataclass(frozen=True)
class ElevationEstimate:
    """
    What the cascade concluded about where the camera was.

    `degrees` is the camera elevation above the horizontal through the vehicle —
    strictly, above the horizontal through WHEEL_CENTRE_HEIGHT_M, see that
    constant — and is positive when the camera was above it. `confidence` runs
    0.0 to 1.0 and never exceeds WHEEL_CONFIDENCE_CEILING. `method` names which
    rung produced the number, so a caller can tell a measurement from a guess
    instead of having to infer it from the confidence alone.
    """

    degrees: float
    confidence: float
    method: str


# ── Shared geometry helpers ────────────────────────────────────────────────────

def _visible_bounds(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
    """The bounding box of anything visible, or None for an empty cutout.

    The alpha > 6 test is the one compositing._visible_bounds uses, so the two
    modules agree about where a vehicle starts and stops.
    """
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
    """
    The row the tyres sit on.

    Deliberately not the lowest solid pixel anywhere: one stray row of mask — a
    remnant of the original ground shadow, a segmentation spike — would move the
    contact line down and every gap measured against it with it. The 0.97
    quantile of each column's lowest solid pixel is the same defence, and for the
    same reason, as compositing._contact_y.
    """
    has, lowest = _column_bottoms(solid)
    if not has.any():
        return None
    return float(np.quantile(lowest[has].astype(np.float64), 0.97))


def _clamped_to_range(theta_deg: float) -> tuple[float, float] | None:
    """
    A rung's raw answer brought inside the plausible range, with the confidence
    factor that costs, or None when it must be thrown away instead.

    Three behaviours, and the third is the important one. A non-finite value —
    arccos of an out-of-domain argument, a zero lever — is rejected outright and
    never clamped. A value within OUT_OF_RANGE_TOLERANCE_DEG of a bound is
    clamped and the rung's confidence halved, because a fit that lands a degree
    past the edge on pixel quantisation is still a measurement. Anything further
    out is REJECTED, and that must not be softened into a clamp: a wheel ratio of
    0.70 at an assumed side-on azimuth inverts to 45.6 deg, which is not a
    photographer on a ladder but a car that was really at a quarter angle or a
    tyre contour that swallowed the wheel arch. Clamping it to 35 deg would
    launder a detection failure into a confident wrong answer at the top of the
    range, which is precisely what the 'assumed' rung exists to prevent.
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
    """
    A rung's confidence, propagated from its own error budget rather than asserted.

    Written once and shared by both measurement rungs on purpose: it is what
    makes their very different ceilings comparable, and what turns rung 2's
    side-on refusal into a consequence of arithmetic instead of a rule someone
    remembered to write.
    """
    if not math.isfinite(sigma_theta_deg) or sigma_theta_deg <= 0:
        return 0.0
    resolved = min(1.0, CONFIDENCE_REFERENCE_SIGMA_DEG / sigma_theta_deg)
    return float(ceiling * resolved * quality)


# ── Rung 1: wheel ellipse ──────────────────────────────────────────────────────

def _chord_ratio(contour: np.ndarray) -> tuple[float, float] | None:
    """
    A tyre's minor-over-major axis ratio, measured from its sides and bottom
    only. Returns (ratio, major_px), or None when the arc could not be sampled.

    THIS IS THE SINGLE MOST IMPORTANT IMPLEMENTATION DECISION IN THE MODULE AND
    IT MUST NOT BE SIMPLIFIED INTO A cv2.fitEllipse CALL. Every real wheel is
    clipped at the top by its own arch, and fitEllipse on a top-truncated ellipse
    is catastrophically biased. Measured on a synthetic side-on wheel whose true
    elevation is 11.16 deg: 0% of the tyre hidden reports 11.10 deg, 5% hidden
    reports 18.37 deg, 10% reports 25.73 deg, 20% reports 37.28 deg and 30%
    reports 46.79 deg. No sanity check on the fit rescues it either — the
    contour-area over ellipse-area fill is 0.999 at the 10% clip that has already
    cost 14 deg, so a fill gate looks perfectly healthy while the answer is
    ruined.

    The arch clips the top and never the flanks or the bottom, so those are what
    is measured. Side-on the ellipse is axis-aligned, which is what makes a
    row scan valid at all — see the module docstring on why this rung runs at no
    other azimuth. For an ellipse of semi-axes a and b, the row whose width is
    f * 2a sits b * sqrt(1 - f^2) from the centre, so its height above the bottom
    is b * (1 - sqrt(1 - f^2)); inverting that at several f and taking the median
    gives b without ever looking at the top of the tyre.
    """
    x, y, width, height = cv2.boundingRect(contour)
    if width < 2 or height < 2:
        return None

    # Filled rather than the raw contour, because a tyre segments as an annulus
    # once the rim is bright enough to fail the darkness test, and a raw row of
    # the annulus is two runs of sidewall rather than one run of tyre.
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
    # The bottom of the tyre lies half a row below the centre of the last row it
    # occupies; the chord crossings below are interpolated in the same row-centre
    # coordinates, so the two are consistent.
    bottom = lowest_row + 0.5

    semi_minor: list[float] = []
    for fraction in WHEEL_CHORD_FRACTIONS:
        target = fraction * major
        crossing = None
        for row in range(lowest_row, highest_row - 1, -1):
            if widths[row] < target:
                continue
            # Every row already passed over is narrower than the target and the
            # row under the lowest one is empty, so the bracket below is always
            # strictly narrower and the interpolation cannot divide by zero.
            below = widths[row + 1] if row < lowest_row else 0.0
            crossing = (row + 1) - (target - below) / (widths[row] - below)
            break
        if crossing is None:
            continue
        chord = 1.0 - math.sqrt(max(0.0, 1.0 - fraction * fraction))
        candidate = (bottom - crossing) / chord
        if candidate > 0:
            semi_minor.append(candidate)

    # One missing crossing is a ragged edge; two is a tyre this scan cannot read.
    if len(semi_minor) < len(WHEEL_CHORD_FRACTIONS) - 1:
        return None
    return float(np.median(semi_minor)) / (major / 2.0), major


def _wheel_ellipse(cutout: Image.Image, angle: str | None) -> ElevationEstimate | None:
    """
    Elevation from the foreshortening of the tyres, or None when it cannot be had.

    RUNS ONLY AT angle == 'side', and that is a departure from REALISM_PLAN.md's
    ordering-by-preference forced by arithmetic rather than taste. Since the
    observable is cos(theta)*cos(phi) and only the product is visible, the
    elevation can only be recovered by dividing the azimuth out, and the azimuth
    term is roughly two orders of magnitude larger than the signal being
    extracted. Head-on and tail-on, cos(phi) is zero: the wheel does not contain
    a noisy amount of elevation information, it contains none, and the inversion
    is a division by zero. At the quarter angles the label spans perhaps 25-65
    deg of true azimuth, over which cos(phi) runs 0.906 to 0.423 — assuming 45
    deg when the truth is 40 deg makes the ratio exceed 1 and there is no
    solution at all, and assuming it when the truth is 50 deg turns a real 11.16
    deg into 26.9 deg. That answer would be a readout of the classifier's azimuth
    error, not a measurement of the camera. With no angle at all the aspect ratio
    separates end-on from oblique but cannot separate side from quarter, which is
    exactly the distinction that matters here.
    """
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

    # Opened before contouring so a tyre that touches a dark sill or a black
    # bumper insert breaks away from it rather than being contoured as one shape.
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
        # A shape reaching the top row of the search band is a body panel
        # carrying on upwards out of it, not a wheel sitting inside it.
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
        # One of the two is not a wheel. Which one is unknowable from here, so
        # neither is used.
        return None

    ratio = float(np.median([item[0] for item in accepted]))
    # The smaller of the two majors drives the noise term, because that is the
    # measurement the median can be dragged by.
    major_px = min(item[1] for item in accepted)
    quality = 1.0 if len(accepted) == 2 else 0.75

    # phi, the azimuth away from side-on, is zero by construction because the rung
    # refused every other angle above. The azimuth is still divided out in full
    # rather than folded away, because minor/major = cos(theta)*cos(phi) is the
    # relationship this module departs from REALISM_PLAN.md over and the next
    # reader must be able to check the code against that argument.
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
    # theta = arccos(ratio), so sigma_theta = sigma_ratio / sin(theta): the
    # uncertainty in degrees blows up as the elevation falls, and the confidence
    # has to fall with it. Below about 3.5 deg it drops under
    # MIN_USEFUL_CONFIDENCE and the rung hands on, because an estimate whose
    # one-sigma band covers the whole plausible range is not a measurement.
    sigma_theta = math.inf if sine <= 0 else math.degrees(sigma_ratio / sine)

    confidence = _confidence_from_sigma(
        WHEEL_CONFIDENCE_CEILING, sigma_theta, quality * range_penalty
    )
    if confidence < MIN_USEFUL_CONFIDENCE:
        return None
    return ElevationEstimate(theta_deg, confidence, "wheel_ellipse")


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

def _azimuth_class(angle: str | None, width: int, height: int) -> tuple[str, bool]:
    """
    Which set of UNDERSIDE_GEOMETRY constants applies, and whether it was guessed.

    An unrecognised label is treated exactly as no label, which is the same
    degradation compositing._angle_profile makes and for the same reason: the day
    the classifier gains a sixth angle, this must produce a weaker answer rather
    than start failing jobs.
    """
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
    """
    Elevation from the height of the see-through gap under the car.

    REALISM_PLAN.md calls this rung "roof-to-underside". The roof half is dropped
    and the method string kept only because the contract fixes it, for three
    reasons: the roof panel is inside the silhouette so alpha cannot see it and
    its colour equals the rest of the car so colour cannot segment it; the near
    roof edge, whose separation from the far edge is the real cue, is an internal
    edge that a cutout does not contain; and the one roof-derived quantity alpha
    does give — the silhouette's width-to-height ratio — changes by only 4.8%
    over 0-17 deg while varying between 2.9 and 3.6 across models, so the
    vehicle's own proportions swamp the signal entirely.

    What is left works because the underbody cavity is background at low
    elevation and fills with the far rocker, the far wheels and the underbody as
    the camera rises. The gap closes, and it closes far faster than the wheel
    ellipse flattens: 1.37% of signal per degree side-on and 18.8% per degree
    end-on, against the wheel's 0.34% per degree.

    THE CEILING IS BELOW RUNG 1'S ON PURPOSE, and the reason is worth having in
    the module rather than in a report. This rung is far MORE sensitive than rung
    1 but its zero point depends on a vehicle dimension nobody has measured. High
    precision, poor accuracy: it resolves CHANGES in camera height well and names
    an ABSOLUTE height badly, so it must never outrank a clean wheel fit even
    though it looks the crisper measurement. That is the correct reading of the
    plan's "coarse but robust", arrived at from the numbers rather than from the
    adjective. Its best case, end-on, is also exactly rung 1's empty case, so the
    two rungs complement each other rather than competing — see the contact-line
    test below for the quarter angles, which neither of them can reach.
    """
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

    # A genuine cutout puts only the contact patches on the line — about 8% of
    # the width side-on and 22% end-on. Much more than that and the silhouette
    # has a flat bottom, which happens two ways and neither can be measured. The
    # mask may have swallowed the original ground shadow; or the camera may be
    # above the saturation angle arctan(c/b), 16.4 deg end-on, past which the
    # lowest thing in the frame stops being the tyres and becomes the valance
    # edge, which runs the full width of the car. Read literally either one is a
    # closed underside gap, that is, a high camera — the one failure this rung
    # could turn into a confidently wrong answer.
    #
    # THE SATURATED CASE THEREFORE CANNOT BE REPORTED AS A LOWER BOUND, which is
    # a departure from the specification this module was written to. The two
    # causes present identical evidence, and one of them says the camera was
    # high while the other says nothing whatever about it, so the honest reading
    # of a flat bottom is that there is nothing here to read.
    if int(on_line.sum()) > UNDERSIDE_BOTTOM_FLAT_MAX * width:
        return None

    # Two contact patches a wheelbase apart, or this is not a car standing on a
    # level line. That test also excludes every quarter-angle photograph, which
    # is worth saying plainly because neither REALISM_PLAN.md nor the arithmetic
    # above anticipated it: off the axis the near front wheel is closer to the
    # camera than the near rear one, so their contact patches project several
    # per cent of the silhouette height apart and there is no level contact line
    # for a gap to be measured against. Between them the two measurement rungs
    # therefore cover 'side' and the two end-on labels only, and both quarters
    # fall through to the prior.
    runs = _runs(on_line)
    if len(runs) < 2 or runs[-1][0] - runs[0][1] < UNDERSIDE_MIN_WHEELBASE_RATIO * width:
        return None

    between = np.zeros(width, dtype=bool)
    between[runs[0][1] + 1:runs[-1][0]] = True
    measurable = between & has & (gap > 0)
    if not measurable.any():
        # Every column between the contact patches is either transparent or
        # sitting on the line itself, so there is no gap here to take a median of.
        return None
    ratio = float(np.median(gap[measurable])) / height

    azimuth_class, assumed = _azimuth_class(angle, width, height)
    clearance, lever = UNDERSIDE_GEOMETRY[azimuth_class]

    # r(theta) = c/H - (b/H) * tan(theta) within the orthographic model, so this
    # is its exact inverse.
    residual = clearance - ratio * REFERENCE_VEHICLE_HEIGHT_M
    theta_deg = math.degrees(math.atan2(residual, lever))

    clamped = _clamped_to_range(theta_deg)
    if clamped is None:
        return None
    theta_deg, range_penalty = clamped

    # d(theta)/d(clearance) = b / (b^2 + residual^2), so CLEARANCE_UNCERTAINTY_M
    # propagates to +-3.2 deg end-on, +-5.7 deg at a quarter and +-25 deg
    # side-on. That last one is more than the entire plausible range, so the
    # side-on refusal falls out of MIN_USEFUL_CONFIDENCE below without anyone
    # having to write it as a rule.
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
    """
    A population prior over how dealers actually shoot, once both measurements
    have declined. Nothing is read from the pixels.

    The confidence is flat and low because there is no measurement to propagate:
    the spread is over photographers, not over pixels, and nobody has measured
    it. ANGLE_PRIOR_CONFIDENCE_NAMED is deliberately only twice the assumed
    rung's floor — a dealer who photographs everything from a stool defeats this
    rung entirely, and the number must not pretend otherwise. It sits above
    'assumed' only because it carries one real bit, that a rear shot is more
    often taken high and a front-quarter low, and below both measurements because
    that bit is a habit rather than an observation.
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
    """
    Estimate the camera elevation of the photograph this cutout came from.

    `cutout` is RGBA: the vehicle on transparency, background already removed and
    plates already blurred, which is the shape PipelineProcessor.process holds
    between _apply_plate_treatment and _place_on_backdrop. `angle` is the shot
    angle when something upstream knows it, one of classification.ANGLES.

    Never raises and never returns None. Each measurement rung runs inside its
    own try/except so that a malformed cutout, a zero-size image, a mode PIL
    cannot convert or an OpenCV error on a degenerate contour lands on the
    assumed rung instead of propagating into the pipeline and failing a job that
    had already succeeded at everything else. HANDOVER.md records a correct run
    that produced nothing usable as needing review rather than as a failure, and
    the same honesty applies here: the last rung reports standing eye level and
    says through method='assumed' that it is a guess.

    ASSUMED_CONFIDENCE is deliberately non-zero. Zero would invite a caller to
    read it as "no information" and skip the horizon alignment entirely, when in
    fact standing eye level is the single most likely answer and applying it is
    better than applying nothing. It is deliberately low so that any policy of
    the form "only shift the backdrop when confidence exceeds X" can exclude it
    with an obvious threshold.
    """
    for rung in (_wheel_ellipse, _roof_underside):
        try:
            estimate = rung(cutout, angle)
        except Exception:  # noqa: BLE001 - see the docstring: a rung may never fail a job
            logger.debug("Elevation rung %s failed; handing on", rung.__name__, exc_info=True)
            continue
        if estimate is not None:
            return estimate

    # No guard around this one: unlike the two rungs above it reads no pixels, so
    # there is nothing in it for an odd cutout to break.
    estimate = _shot_angle(angle)
    if estimate is not None:
        return estimate

    # Standing eye level at the typical shooting distance, which is inside the
    # plausible range by construction — that is what guarantees the value
    # returned by this function is always finite and always in range.
    return ElevationEstimate(STANDING_ELEVATION_DEG, ASSUMED_CONFIDENCE, "assumed")
