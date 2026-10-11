import math

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

import classification
import elevation


# ── The car these tests render ─────────────────────────────────────────────────

HALF_LENGTH = elevation.REFERENCE_VEHICLE_LENGTH_M / 2.0
HALF_WIDTH = elevation.REFERENCE_VEHICLE_WIDTH_M / 2.0
ROOF_HEIGHT = elevation.REFERENCE_VEHICLE_HEIGHT_M
WHEEL_RADIUS = elevation.WHEEL_CENTRE_HEIGHT_M

AXLE_X = 0.775
AXLE_Y = 1.35

HALF_TREAD = 0.1025

RIM_RADIUS = 0.2032

ROCKER_Z, ROCKER_LEVER = elevation.UNDERSIDE_GEOMETRY["side"]
VALANCE_Z, VALANCE_LEVER = elevation.UNDERSIDE_GEOMETRY["end"]
ROCKER_X = AXLE_X + ROCKER_LEVER
VALANCE_Y = AXLE_Y + VALANCE_LEVER

UNDERBODY_TOP_Z = 0.42

BODY_COLOUR = (176, 62, 58)
TYRE_COLOUR = (28, 28, 30)
RIM_COLOUR = (185, 185, 190)

BODY_PPM = 180
WHEEL_PPM = 700

CANVAS_MARGIN = 24

CIRCLE_SAMPLES = 128


def projector(elevation_deg, azimuth_deg, pixels_per_metre):
    """The orthographic projection elevation.py's geometry is derived under."""
    t, p = math.radians(elevation_deg), math.radians(azimuth_deg)
    view = np.array([math.cos(t) * math.cos(p), math.cos(t) * math.sin(p), math.sin(t)])
    right = np.array([-math.sin(p), math.cos(p), 0.0])
    up = np.cross(view, right)

    def project(points):
        pts = np.asarray(points, dtype=np.float64)
        return np.stack([pts @ right, -(pts @ up)], axis=1) * pixels_per_metre

    return project


def box(x0, x1, y0, y1, z0, z1):
    """The six faces of an axis-aligned box, whose union is its silhouette."""
    corner = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    return [
        [corner[i] for i in face]
        for face in ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4),
                     (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5))
    ]


BODY_POLYGONS = (
    box(-HALF_WIDTH, HALF_WIDTH, -HALF_LENGTH, HALF_LENGTH, UNDERBODY_TOP_Z, ROOF_HEIGHT)
    + box(-ROCKER_X, ROCKER_X, -AXLE_Y, AXLE_Y, ROCKER_Z, UNDERBODY_TOP_Z)
    + box(-ROCKER_X, ROCKER_X, AXLE_Y, VALANCE_Y, VALANCE_Z, UNDERBODY_TOP_Z)
    + box(-ROCKER_X, ROCKER_X, -VALANCE_Y, -AXLE_Y, VALANCE_Z, UNDERBODY_TOP_Z)
)

WHEEL_CENTRES = [(x, y) for x in (-AXLE_X, AXLE_X) for y in (-AXLE_Y, AXLE_Y)]


def wheel_parts(centre, tyre_colour):
    """One tyre as a short cylinder: two sidewall discs, the tread between them, and a
    lighter rim disc on the outer face.
    """
    x0, y0 = centre
    angles = [2 * math.pi * i / CIRCLE_SAMPLES for i in range(CIRCLE_SAMPLES)]
    ring = [
        (y0 + WHEEL_RADIUS * math.cos(a), WHEEL_RADIUS + WHEEL_RADIUS * math.sin(a))
        for a in angles
    ]
    inner_x = x0 - math.copysign(HALF_TREAD, x0)
    outer_x = x0 + math.copysign(HALF_TREAD, x0)
    inner = [(inner_x, y, z) for y, z in ring]
    outer = [(outer_x, y, z) for y, z in ring]

    parts = [(centre, inner, tyre_colour), (centre, outer, tyre_colour)]
    for i in range(CIRCLE_SAMPLES):
        j = (i + 1) % CIRCLE_SAMPLES
        parts.append((centre, [inner[i], inner[j], outer[j], outer[i]], tyre_colour))
    parts.append((centre, [
        (outer_x, y0 + RIM_RADIUS * math.cos(a), WHEEL_RADIUS + RIM_RADIUS * math.sin(a))
        for a in angles
    ], RIM_COLOUR))
    return parts


def synthetic_cutout(elevation_deg, azimuth_deg=0.0, *, pixels_per_metre=BODY_PPM,
                     hide_wheel_fraction=0.0, tyre_colour=TYRE_COLOUR):
    """An RGBA cutout of the reference car, seen from a known camera elevation."""
    project = projector(elevation_deg, azimuth_deg, pixels_per_metre)

    camera_side = math.cos(math.radians(azimuth_deg)) > 1e-6
    near = [c for c in WHEEL_CENTRES if camera_side and c[0] > 0]
    far = [c for c in WHEEL_CENTRES if c not in near]

    parts = []
    for centre in far:
        parts.extend(wheel_parts(centre, tyre_colour))
    parts.extend((None, polygon, BODY_COLOUR) for polygon in BODY_POLYGONS)
    for centre in near:
        parts.extend(wheel_parts(centre, tyre_colour))

    drawn = [(key, project(polygon), colour) for key, polygon, colour in parts]
    every = np.concatenate([points for _, points, _ in drawn])
    origin = every.min(axis=0) - CANVAS_MARGIN
    extent = np.ceil(every.max(axis=0) - origin).astype(int) + CANVAS_MARGIN

    canvas = Image.new("RGBA", (int(extent[0]), int(extent[1])), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for _, points, colour in drawn:
        draw.polygon([tuple(q) for q in points - origin], fill=(*colour, 255))

    if hide_wheel_fraction > 0:
        for centre in WHEEL_CENTRES:
            tyre = np.concatenate([p for k, p, _ in drawn if k == centre]) - origin
            (x0, y0), (x1, y1) = tyre.min(axis=0), tyre.max(axis=0)
            draw.rectangle(
                [x0 - 1, y0 - 1, x1 + 1, y0 + (y1 - y0) * hide_wheel_fraction],
                fill=(*BODY_COLOUR, 255),
            )
    return canvas


def projected_wheel_axis_ratio(elevation_deg, azimuth_deg):
    """The minor-over-major axis ratio of one wheel, from the projection alone."""
    ring = [
        (0.0, WHEEL_RADIUS * math.cos(a), WHEEL_RADIUS + WHEEL_RADIUS * math.sin(a))
        for a in (2 * math.pi * i / 4000 for i in range(4000))
    ]
    points = projector(elevation_deg, azimuth_deg, 2000)(ring)
    points = (points - points.min(axis=0) + 5).astype(np.float32)
    _, (first, second), _ = cv2.fitEllipse(points.reshape(-1, 1, 2))
    return min(first, second) / max(first, second)


def solid_bounds(cutout):
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha >= 128)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ── The generator, before anything rests on it ─────────────────────────────────

@pytest.mark.parametrize("elevation_deg", [0.0, 4.61, 11.16, 17.43, 35.0, 60.0, 85.0])
@pytest.mark.parametrize("azimuth_deg", [0.0, 30.0, 45.0, 60.0, 90.0])
def test_synthetic_wheel_matches_the_projection_law(elevation_deg, azimuth_deg):
    """If the generator does not project a wheel the way the geometry says, every other
    assertion in this file is measuring the wrong thing and passing.
    """
    predicted = abs(
        math.cos(math.radians(elevation_deg)) * math.cos(math.radians(azimuth_deg))
    )
    assert projected_wheel_axis_ratio(elevation_deg, azimuth_deg) == pytest.approx(
        predicted, abs=0.005
    )


# ── The geometry REALISM_PLAN.md gets backwards ────────────────────────────────

def test_wheel_ratio_follows_cosine_not_sine_of_elevation():
    """The regression for this module's one documented departure."""
    ground = projected_wheel_axis_ratio(0.0, 0.0)
    raised = projected_wheel_axis_ratio(60.0, 0.0)

    assert ground == pytest.approx(1.0, abs=0.005)
    assert raised == pytest.approx(0.5, abs=0.005)
    assert raised < ground, "a raised camera must flatten a wheel, not round it"


def test_overhead_camera_sees_a_wheel_as_a_line():
    """REALISM_PLAN.md's second example — "from directly above, a circle" — is simply
    false, and this is the case that shows it.
    """
    assert projected_wheel_axis_ratio(85.0, 0.0) < 0.10


# ── Rung 1: the wheel ellipse ──────────────────────────────────────────────────

def test_wheel_rung_recovers_a_high_camera():
    """The end-to-end check that the inversion is arccos and not arcsin."""
    estimate = elevation.estimate_elevation(
        synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method == "wheel_ellipse"
    assert estimate.degrees == pytest.approx(18.0, abs=2.0)


def test_wheel_rung_survives_wheel_arch_occlusion():
    """The defect that makes the chord scan non-negotiable: cv2.fitEllipse on a tyre
    clipped by its own wheel arch is catastrophically biased.
    """
    answers = [
        elevation.estimate_elevation(
            synthetic_cutout(11.16, 0.0, pixels_per_metre=WHEEL_PPM,
                             hide_wheel_fraction=hidden),
            "side",
        )
        for hidden in (0.0, 0.10, 0.20)
    ]

    assert all(answer.method == "wheel_ellipse" for answer in answers)
    assert max(a.degrees for a in answers) - min(a.degrees for a in answers) <= 2.0


@pytest.mark.parametrize("angle", ["front", "rear"])
def test_head_on_never_uses_the_wheel_rung(angle):
    """Head-on cos(phi) is zero, so the observable cos(theta)cos(phi) is zero whatever
    the elevation and inverting it divides by zero.
    """
    cutout = synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM)

    assert elevation.estimate_elevation(cutout, "side").method == "wheel_ellipse"
    assert elevation.estimate_elevation(cutout, angle).method != "wheel_ellipse"


@pytest.mark.parametrize("angle", ["front_quarter", "rear_quarter"])
def test_quarter_angles_never_use_the_wheel_rung(angle):
    """A quarter label spans perhaps 25 to 65 degrees of true azimuth, over which
    cos(phi) runs 0.906 to 0.423.
    """
    cutout = synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM)

    assert elevation.estimate_elevation(cutout, "side").method == "wheel_ellipse"
    assert elevation.estimate_elevation(cutout, angle).method != "wheel_ellipse"


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

@pytest.mark.parametrize("truth", [8.0, 11.16, 14.0])
def test_underside_rung_recovers_a_known_elevation_when_the_wheels_cannot_be_found(truth):
    """The rung that has to carry the end-on photographs, where the wheel ellipse is
    mathematically empty.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 90.0, tyre_colour=BODY_COLOUR), "front"
    )

    assert estimate.method == "roof_underside"
    assert estimate.degrees == pytest.approx(truth, abs=4.0)


@pytest.mark.parametrize("truth", [4.61, 11.16, 17.43])
def test_underside_rung_declines_side_on(truth):
    """Side-on the lever from the rocker face to the contact patch is 0.105 m, so the
    0.05 m of unknown ground clearance across the fleet is worth about 25 degrees —
    more than the entire plausible range.
    """
    cutout = synthetic_cutout(truth, 0.0, tyre_colour=BODY_COLOUR)

    assert elevation.estimate_elevation(cutout, None).method == "roof_underside"
    assert elevation.estimate_elevation(cutout, "side").method in ("shot_angle", "assumed")


def test_quarter_angle_photographs_reach_neither_measurement_rung():
    """A narrowing neither REALISM_PLAN.md nor this module's specification saw."""
    estimate = elevation.estimate_elevation(synthetic_cutout(11.16, 45.0), "front_quarter")

    assert estimate.method == "shot_angle"


def test_a_shadow_filled_underside_is_not_read_as_a_high_camera():
    """The failure this rung could turn into a confident wrong answer: a mask that
    swallowed the original ground shadow has a flat bottom, and a flat bottom read
    literally is a closed underside gap, that is, a camera held high.
    """
    cutout = synthetic_cutout(5.0, 90.0, tyre_colour=BODY_COLOUR)
    assert elevation.estimate_elevation(cutout, "front").method == "roof_underside"

    left, top, right, bottom = solid_bounds(cutout)
    ImageDraw.Draw(cutout).rectangle(
        [left, bottom - (bottom - top) // 4, right, bottom], fill=(40, 38, 38, 255)
    )

    assert elevation.estimate_elevation(cutout, "front").method != "roof_underside"


def test_a_closed_underside_gap_is_refused_rather_than_reported():
    """Above about 16 degrees end-on the gap has closed and the lowest thing in the
    frame is the valance edge, which runs the full width of the car.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(25.0, 90.0, tyre_colour=BODY_COLOUR), "front"
    )

    assert estimate.method != "roof_underside"


# ── The lower rungs, and the contract ──────────────────────────────────────────

def test_shot_angle_rung_is_used_when_nothing_is_measurable():
    """A featureless blob has no tyres to foreshorten and no underside to see through,
    so both measurements decline and all that is left is how dealers are known to
    shoot: overhead for the rear.
    """
    blob = Image.new("RGBA", (600, 300), (90, 90, 90, 255))
    estimate = elevation.estimate_elevation(blob, "rear")

    assert estimate.method == "shot_angle"
    assert estimate.degrees == pytest.approx(elevation.RAISED_ELEVATION_DEG)


@pytest.mark.parametrize("cutout", [
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)),
    Image.new("RGBA", (1, 1), (10, 10, 10, 255)),
    Image.new("RGBA", (300, 200), (90, 90, 90, 255)),
    Image.new("RGBA", (400, 1), (30, 30, 30, 255)),
    Image.new("L", (200, 120), 128).convert("RGBA"),
    Image.new("RGBA", (0, 0)),
], ids=["transparent", "one-pixel", "opaque", "single-row", "from-greyscale", "zero-size"])
@pytest.mark.parametrize("angle", [None, "side", "front", "rear_quarter", "overhead"])
def test_estimate_never_raises_and_never_returns_none(cutout, angle):
    """A job that had already classified, detected, matted and de-plated a photograph
    must not then fail on a measurement it was only ever going to record.
    """
    estimate = elevation.estimate_elevation(cutout, angle)

    assert estimate is not None
    assert estimate.method in elevation.ELEVATION_METHODS


@pytest.mark.parametrize("truth,azimuth,angle,ppm", [
    (0.0, 0.0, "side", WHEEL_PPM),
    (11.16, 0.0, "side", WHEEL_PPM),
    (35.0, 0.0, "side", WHEEL_PPM),
    (60.0, 0.0, "side", WHEEL_PPM),
    (85.0, 0.0, "side", WHEEL_PPM),
    (0.0, 90.0, "front", BODY_PPM),
    (11.16, 90.0, "rear", BODY_PPM),
    (25.0, 90.0, "front", BODY_PPM),
    (11.16, 45.0, "front_quarter", BODY_PPM),
    (11.16, 45.0, None, BODY_PPM),
])
def test_result_is_always_inside_the_plausible_range(truth, azimuth, angle, ppm):
    """The guarantee downstream code is allowed to rely on."""
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, azimuth, pixels_per_metre=ppm), angle
    )

    assert math.isfinite(estimate.degrees)
    assert elevation.MIN_ELEVATION_DEG <= estimate.degrees <= elevation.MAX_ELEVATION_DEG
    assert 0.0 <= estimate.confidence <= 1.0
    assert estimate.method in elevation.ELEVATION_METHODS


def test_an_impossible_measurement_is_rejected_not_clamped():
    """A side-on tyre with an axis ratio of 0.55 inverts to 56.6 degrees, which is not a
    photographer on a ladder — it is a car that was really at a quarter angle, or a
    contour that swallowed the wheel arch.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(56.63, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method != "wheel_ellipse"
    assert estimate.degrees != elevation.MAX_ELEVATION_DEG


def test_a_measurement_just_past_the_range_is_kept_but_costs_confidence():
    """The other half of the same rule, and the reason it is a tolerance rather than a
    hard edge.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(38.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method == "wheel_ellipse"
    assert estimate.degrees == elevation.MAX_ELEVATION_DEG
    assert estimate.confidence <= elevation.WHEEL_CONFIDENCE_CEILING / 2


# ── The sensitivity finding, written as tests ──────────────────────────────────

def test_confidence_falls_as_the_elevation_falls():
    """Because theta = arccos(ratio), the uncertainty in degrees is sigma_ratio over
    sin(theta), so it blows up as the camera comes down.
    """
    low = elevation.estimate_elevation(
        synthetic_cutout(5.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )
    high = elevation.estimate_elevation(
        synthetic_cutout(20.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert high.method == "wheel_ellipse"
    assert high.confidence > low.confidence + 0.2


@pytest.mark.parametrize("truth", [15.0, 17.43, 20.0, 25.0])
def test_a_high_camera_is_recovered_closely(truth):
    """Above about 15 degrees sin(theta) is large enough that the inverse is well
    conditioned, so this is the band where a wrong constant or a sign slip in the
    chord relation would show as an offset rather than hide inside the noise.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.degrees == pytest.approx(truth, abs=2.0)


@pytest.mark.parametrize("truth", [8.0, 11.16])
def test_a_middling_camera_is_recovered_loosely(truth):
    """Deliberately six degrees and not two."""
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.degrees == pytest.approx(truth, abs=6.0)


@pytest.mark.parametrize("truth", [3.0, 5.0])
def test_a_low_camera_is_not_claimed_to_be_measured(truth):
    """Below about 3.5 degrees the propagated one-sigma band covers the whole plausible
    range, and an estimate that wide is not a measurement.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.confidence < 0.25


def test_a_raised_camera_reads_higher_than_a_standing_or_crouching_one():
    """The strongest claim the analysis supports, and the one that stops a later change
    quietly reversing the sign of the relationship: this estimator can tell a
    genuinely high camera from a genuinely low one.
    """
    recovered = [
        elevation.estimate_elevation(
            synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
        ).degrees
        for truth in (
            elevation.CROUCHING_ELEVATION_DEG,
            elevation.STANDING_ELEVATION_DEG,
            elevation.RAISED_ELEVATION_DEG,
        )
    ]
    crouching, standing, raised = recovered

    assert raised > crouching + 3.0
    assert raised > standing + 3.0


# ── The one integration point Stage 1 has ──────────────────────────────────────

def test_the_pipeline_cutout_and_the_classifier_vocabulary_are_both_accepted():
    """Pins the two vocabularies together without importing anything heavy —
    classification.py keeps torch inside its loader, so this costs nothing.
    """
    cutout = synthetic_cutout(11.16, 0.0)
    assert cutout.mode == "RGBA"

    for angle in (*classification.ANGLES, None):
        estimate = elevation.estimate_elevation(cutout, angle)
        assert estimate.method in elevation.ELEVATION_METHODS
        assert elevation.MIN_ELEVATION_DEG <= estimate.degrees <= elevation.MAX_ELEVATION_DEG

