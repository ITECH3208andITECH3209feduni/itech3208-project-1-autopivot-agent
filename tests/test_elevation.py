# Tests for estimating the camera elevation of a source photograph.
#
# elevation.py imports only cv2, numpy and PIL — no torch, no model, no
# database — so these run wherever those three are installed:
#
#     pytest tests/test_elevation.py -v
#
# Every cutout below comes out of `synthetic_cutout`, which renders the exact
# orthographic projection of a car of known dimensions seen from a known camera
# elevation. Nothing here is drawn by eye and no expected answer is tuned to the
# implementation: the truth is analytic. The first test checks the generator
# against that geometry before any other test rests on it.
#
# Two resolutions are used, and the difference between them is itself a finding.
# The underside rung reads the alpha channel and is happy at BODY_PPM, where a
# car is a few hundred pixels across. The wheel rung is measuring an axis ratio
# that moves by four percentage points across the whole plausible range, so it
# needs WHEEL_PPM — a 442-pixel wheel, which is what a car filling a 3000-pixel
# photograph gives.

import math

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

import classification
import elevation


# ── The car these tests render ─────────────────────────────────────────────────

# Taken from elevation.py's own reference vehicle rather than chosen here, so
# that the car being rendered is by construction the car the module assumes. A
# reference dimension edited there moves these synthetics with it instead of
# leaving the tests quietly measuring a different vehicle.
HALF_LENGTH = elevation.REFERENCE_VEHICLE_LENGTH_M / 2.0
HALF_WIDTH = elevation.REFERENCE_VEHICLE_WIDTH_M / 2.0
ROOF_HEIGHT = elevation.REFERENCE_VEHICLE_HEIGHT_M
WHEEL_RADIUS = elevation.WHEEL_CENTRE_HEIGHT_M

# Track and wheelbase of the same sedan: wheels 1.55 m apart across the car and
# 2.70 m along it, both comfortably inside the body, as they are on a real car.
AXLE_X = 0.775
AXLE_Y = 1.35

# A 205-section tyre. The tread width is not decoration: a zero-thickness disc
# projects to a line when the camera is head-on, which leaves no contact patch
# for the underside rung to find a wheelbase between, and a real photograph
# plainly has two. It is also what makes the contact columns come out at the 22%
# of the width that UNDERSIDE_BOTTOM_FLAT_MAX is set against.
HALF_TREAD = 0.1025

# The 16-inch rim inside that tyre, 406.4 mm across. It is drawn lighter than the
# rubber so the darkness threshold leaves a hole in the middle, which is how a
# real wheel segments and the case `elevation._chord_ratio` fills its contour for.
RIM_RADIUS = 0.2032

# The underbody, built directly out of the constants the underside rung inverts,
# so the synthetic car has exactly the ground clearance and the lever the module
# believes a car has. Side-on the lowest visible edge between the wheels is the
# rocker; end-on it is the valance, which sits higher and further forward.
ROCKER_Z, ROCKER_LEVER = elevation.UNDERSIDE_GEOMETRY["side"]
VALANCE_Z, VALANCE_LEVER = elevation.UNDERSIDE_GEOMETRY["end"]
ROCKER_X = AXLE_X + ROCKER_LEVER
VALANCE_Y = AXLE_Y + VALANCE_LEVER

# Where the sills and valances stop and the body proper begins. Any height above
# the tyre's widest row will do — it only has to keep the main body out of the
# way of the underside gap.
UNDERBODY_TOP_Z = 0.42

# Saturated red for the paint and a near-neutral black for the rubber, which is
# the discrimination TYRE_SATURATION_MAX and TYRE_LIGHTNESS_CEILING are drawn
# to make: the body is L=109, S=171 and the tyre L=27, S=17.
BODY_COLOUR = (176, 62, 58)
TYRE_COLOUR = (28, 28, 30)
RIM_COLOUR = (185, 185, 190)

BODY_PPM = 180
WHEEL_PPM = 700

CANVAS_MARGIN = 24

# How finely a circle is polygonised. At 128 points the sagitta is 0.07 px on a
# 442 px wheel, so the drawn tyre is the true projected ellipse to well inside a
# pixel and the generator adds no error the estimator could trip over.
CIRCLE_SAMPLES = 128


def projector(elevation_deg, azimuth_deg, pixels_per_metre):
    """
    The orthographic projection elevation.py's geometry is derived under.

    `view` is the unit vector from the car towards the camera, `right` the image
    x axis and `up` the image y axis; the y component is negated so that a
    greater height in the world is a smaller row on the canvas.
    """
    t, p = math.radians(elevation_deg), math.radians(azimuth_deg)
    view = np.array([math.cos(t) * math.cos(p), math.cos(t) * math.sin(p), math.sin(t)])
    right = np.array([-math.sin(p), math.cos(p), 0.0])
    up = np.cross(view, right)

    def project(points):
        pts = np.asarray(points, dtype=np.float64)
        return np.stack([pts @ right, -(pts @ up)], axis=1) * pixels_per_metre

    return project


def box(x0, x1, y0, y1, z0, z1):
    """The six faces of an axis-aligned box, whose union is its silhouette.

    Filling all six faces rather than taking a convex hull is what keeps the
    generator honest: there is no hull code here to get subtly wrong, and the
    union of six projected quadrilaterals is the projection of the box exactly.
    """
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
    """One tyre as a short cylinder: two sidewall discs, the tread between them,
    and a lighter rim disc on the outer face.

    A cylinder rather than a bare disc because a disc is zero-thickness, and the
    projection of a zero-thickness disc head-on is a line with no contact patch
    under it for the underside rung to find a wheelbase between.
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
    """
    An RGBA cutout of the reference car, seen from a known camera elevation.

    `azimuth_deg` is measured away from side-on, matching the phi of the module:
    0 is a full side profile and 90 is head-on. The underside gap appears by
    construction rather than by being drawn — the body starts at the rocker
    height and the wheels are separate solids, so the region between them below
    the sill is simply untouched, and it closes at exactly the rate the geometry
    says it does. One generator therefore exercises both measurement rungs and
    neither rung's expected answer is hand-tuned.
    """
    project = projector(elevation_deg, azimuth_deg, pixels_per_metre)

    # Far wheels, then the body over them, then the camera-side wheels on top. A
    # box body has no arches cut into it, so painting the near pair last is what
    # stands in for the arch; leaving the far pair underneath is what lets a low
    # camera still see them through the underbody gap, as a photograph does.
    # Head-on neither pair is nearer, and both are drawn under the body, where
    # the parts below the valance show — which is where the contact patches are.
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

    # The wheel arch, reproduced as the thing that actually happens: body paint
    # covering the top of the tyre, which is what destroys a cv2.fitEllipse fit.
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
    """The minor-over-major axis ratio of one wheel, from the projection alone.

    Deliberately not measured off a rendered cutout: this is the geometry the
    whole module rests on, so it is checked against the maths with no
    rasterisation, no segmentation and no estimator in the way.
    """
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
    """
    If the generator does not project a wheel the way the geometry says, every
    other assertion in this file is measuring the wrong thing and passing.

    The law: a circle of unit normal n seen along v projects to an ellipse whose
    major axis is the true diameter and whose minor over major is |n . v|. A
    wheel's normal is horizontal and lateral, so that is |cos(theta)cos(phi)|.
    """
    predicted = abs(
        math.cos(math.radians(elevation_deg)) * math.cos(math.radians(azimuth_deg))
    )
    assert projected_wheel_axis_ratio(elevation_deg, azimuth_deg) == pytest.approx(
        predicted, abs=0.005
    )


# ── The geometry REALISM_PLAN.md gets backwards ────────────────────────────────

def test_wheel_ratio_follows_cosine_not_sine_of_elevation():
    """
    The regression for this module's one documented departure. REALISM_PLAN.md's
    Phase 1 says a wheel's axis ratio is "approximately the sine of the viewing
    elevation ... from directly above, a circle". It is the cosine, and a raised
    camera therefore FLATTENS a wheel rather than opening it out.

    At ground level the sine rule predicts 0.00 and the cosine rule 1.00; from
    60 degrees above, the sine rule predicts 0.87 and the cosine rule 0.50. The
    two are not a refinement of one another, they disagree about the direction
    of the relationship, and an estimator built on the wrong one reports a
    photograph taken from 60 degrees up as one taken from 30.
    """
    ground = projected_wheel_axis_ratio(0.0, 0.0)
    raised = projected_wheel_axis_ratio(60.0, 0.0)

    assert ground == pytest.approx(1.0, abs=0.005)
    assert raised == pytest.approx(0.5, abs=0.005)
    assert raised < ground, "a raised camera must flatten a wheel, not round it"


def test_overhead_camera_sees_a_wheel_as_a_line():
    """
    REALISM_PLAN.md's second example — "from directly above, a circle" — is
    simply false, and this is the case that shows it. From a helicopter over a
    car the tyres are edge-on, because a wheel's axis is horizontal.
    """
    assert projected_wheel_axis_ratio(85.0, 0.0) < 0.10


# ── Rung 1: the wheel ellipse ──────────────────────────────────────────────────

def test_wheel_rung_recovers_a_high_camera():
    """
    The end-to-end check that the inversion is arccos and not arcsin. A side-on
    photograph from 18 degrees up gives an axis ratio of 0.951; arccos returns
    the 18 degrees, arcsin returns 72, which falls outside the plausible range
    and would be thrown away, so an arcsin implementation does not merely answer
    badly here — it stops answering at all.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method == "wheel_ellipse"
    assert estimate.degrees == pytest.approx(18.0, abs=2.0)


def test_wheel_rung_survives_wheel_arch_occlusion():
    """
    The defect that makes the chord scan non-negotiable: cv2.fitEllipse on a
    tyre clipped by its own wheel arch is catastrophically biased. Run over the
    three cutouts this test renders, whose true elevation is 11.16 degrees,
    fitting the tyre contour instead reports 14.7 degrees with nothing hidden,
    18.5 with a tenth of the tyre hidden and 33.1 with a fifth — not merely
    noisy but not even monotonic. A contour-area over ellipse-area sanity check
    does not rescue it either: the fill is still 0.994 at the tenth that has
    already cost seven degrees.

    Measuring the flanks and the bottom, which the arch never touches, must give
    the same answer whatever is painted over the top.
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
    """
    Head-on cos(phi) is zero, so the observable cos(theta)cos(phi) is zero
    whatever the elevation and inverting it divides by zero. The wheel does not
    hold a noisy amount of elevation information here; it holds none.

    The photograph handed over is a side-on render this rung demonstrably can
    measure, because that is the only way to show the refusal is the label's
    doing rather than something about the pixels.
    """
    cutout = synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM)

    assert elevation.estimate_elevation(cutout, "side").method == "wheel_ellipse"
    assert elevation.estimate_elevation(cutout, angle).method != "wheel_ellipse"


@pytest.mark.parametrize("angle", ["front_quarter", "rear_quarter"])
def test_quarter_angles_never_use_the_wheel_rung(angle):
    """
    A quarter label spans perhaps 25 to 65 degrees of true azimuth, over which
    cos(phi) runs 0.906 to 0.423. Assume 45 degrees when the truth is 50 and a
    real 11.16 degree elevation is reported as 26.9; assume it when the truth is
    40 and the ratio exceeds one and there is no solution at all. The answer
    would be a readout of the classifier's azimuth error, not a measurement of
    the camera, so the rung must decline rather than produce it — and, as above,
    it must decline on the label even when the tyres are perfectly measurable.
    """
    cutout = synthetic_cutout(18.0, 0.0, pixels_per_metre=WHEEL_PPM)

    assert elevation.estimate_elevation(cutout, "side").method == "wheel_ellipse"
    assert elevation.estimate_elevation(cutout, angle).method != "wheel_ellipse"


# ── Rung 2: the underside gap ──────────────────────────────────────────────────

@pytest.mark.parametrize("truth", [8.0, 11.16, 14.0])
def test_underside_rung_recovers_a_known_elevation_when_the_wheels_cannot_be_found(truth):
    """
    The rung that has to carry the end-on photographs, where the wheel ellipse
    is mathematically empty. The tyres are painted the body colour so the
    darkness threshold finds nothing and rung 1 cannot answer even if it wanted
    to, leaving the see-through gap under the car as the only measurement.

    Four degrees is the honest tolerance and not a slack one: the rung's zero
    point is a ground clearance nobody has measured, and CLEARANCE_UNCERTAINTY_M
    alone is worth about three degrees end-on.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 90.0, tyre_colour=BODY_COLOUR), "front"
    )

    assert estimate.method == "roof_underside"
    assert estimate.degrees == pytest.approx(truth, abs=4.0)


@pytest.mark.parametrize("truth", [4.61, 11.16, 17.43])
def test_underside_rung_declines_side_on(truth):
    """
    Side-on the lever from the rocker face to the contact patch is 0.105 m, so
    the 0.05 m of unknown ground clearance across the fleet is worth about 25
    degrees — more than the entire plausible range. The refusal is not written
    as a rule anywhere; it falls out of the same confidence arithmetic every
    other rung uses, which is the point of computing confidence from a sigma.

    The control is what keeps this from being a test that passes for the wrong
    reason: told nothing about the azimuth, the rung reads the very same pixels
    and does answer. So the silhouette is measurable and it is the side-on lever,
    not a missing wheelbase or a flat bottom, that stops the answer being used.
    """
    cutout = synthetic_cutout(truth, 0.0, tyre_colour=BODY_COLOUR)

    assert elevation.estimate_elevation(cutout, None).method == "roof_underside"
    assert elevation.estimate_elevation(cutout, "side").method in ("shot_angle", "assumed")


def test_quarter_angle_photographs_reach_neither_measurement_rung():
    """
    A narrowing neither REALISM_PLAN.md nor this module's specification saw. Off
    the axis the near front wheel is closer to the camera than the near rear
    one, so their contact patches project several per cent of the silhouette
    height apart and the car is not standing on a level line at all. There is
    then no contact line to measure a gap against, and the wheelbase test
    refuses the photograph. Rung 1 has already refused it for the azimuth, so a
    quarter shot is answered by the prior — which is worth pinning, because a
    later change that quietly let a quarter shot through either rung would be
    reporting the classifier's azimuth error as a camera height.
    """
    estimate = elevation.estimate_elevation(synthetic_cutout(11.16, 45.0), "front_quarter")

    assert estimate.method == "shot_angle"


def test_a_shadow_filled_underside_is_not_read_as_a_high_camera():
    """
    The failure this rung could turn into a confident wrong answer: a mask that
    swallowed the original ground shadow has a flat bottom, and a flat bottom
    read literally is a closed underside gap, that is, a camera held high. The
    control below measures the same photograph, so the refusal is caused by the
    filled shadow and not by anything else about the render.
    """
    cutout = synthetic_cutout(5.0, 90.0, tyre_colour=BODY_COLOUR)
    assert elevation.estimate_elevation(cutout, "front").method == "roof_underside"

    left, top, right, bottom = solid_bounds(cutout)
    ImageDraw.Draw(cutout).rectangle(
        [left, bottom - (bottom - top) // 4, right, bottom], fill=(40, 38, 38, 255)
    )

    assert elevation.estimate_elevation(cutout, "front").method != "roof_underside"


def test_a_closed_underside_gap_is_refused_rather_than_reported():
    """
    Above about 16 degrees end-on the gap has closed and the lowest thing in the
    frame is the valance edge, which runs the full width of the car. This module
    departs from its specification by refusing that case instead of reporting
    the saturation angle as a lower bound, and the reason is that a closed gap
    and a mask that swallowed the ground shadow present identical evidence — one
    of them says the camera was high and the other says nothing at all, so the
    honest reading of a flat bottom is that there is nothing there to read.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(25.0, 90.0, tyre_colour=BODY_COLOUR), "front"
    )

    assert estimate.method != "roof_underside"


# ── The lower rungs, and the contract ──────────────────────────────────────────

def test_shot_angle_rung_is_used_when_nothing_is_measurable():
    """
    A featureless blob has no tyres to foreshorten and no underside to see
    through, so both measurements decline and all that is left is how dealers
    are known to shoot: overhead for the rear. Recording that as 'shot_angle'
    rather than as a measurement is what stops a downstream horizon shift
    trusting a population habit as if it were an observation.
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
    """
    A job that had already classified, detected, matted and de-plated a
    photograph must not then fail on a measurement it was only ever going to
    record. The unrecognised 'overhead' label is the same contract
    compositing._angle_profile keeps and for the same reason: the day the
    classifier gains a sixth angle this must degrade, not start failing jobs.
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
    """
    The guarantee downstream code is allowed to rely on. An 85-degree render is
    a drone shot rather than a dealer walking round a lot, and it must come back
    as something inside the range with a low confidence rather than as a number
    Phase 1 would try to select a backdrop variant with.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, azimuth, pixels_per_metre=ppm), angle
    )

    assert math.isfinite(estimate.degrees)
    assert elevation.MIN_ELEVATION_DEG <= estimate.degrees <= elevation.MAX_ELEVATION_DEG
    assert 0.0 <= estimate.confidence <= 1.0
    assert estimate.method in elevation.ELEVATION_METHODS


def test_an_impossible_measurement_is_rejected_not_clamped():
    """
    A side-on tyre with an axis ratio of 0.55 inverts to 56.6 degrees, which is
    not a photographer on a ladder — it is a car that was really at a quarter
    angle, or a contour that swallowed the wheel arch. Clamping it to the top of
    the range would launder a detection failure into a confident wrong answer at
    exactly the elevation that most distorts a composite, which is precisely
    what the 'assumed' rung exists to prevent.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(56.63, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method != "wheel_ellipse"
    assert estimate.degrees != elevation.MAX_ELEVATION_DEG


def test_a_measurement_just_past_the_range_is_kept_but_costs_confidence():
    """
    The other half of the same rule, and the reason it is a tolerance rather
    than a hard edge. A render from 38 degrees is three degrees past the top of
    the plausible range, which is the sort of overshoot pixel quantisation
    produces, so it is clamped to the bound and the rung's confidence halved —
    thrown away it would be, twenty degrees out, but not here.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(38.0, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.method == "wheel_ellipse"
    assert estimate.degrees == elevation.MAX_ELEVATION_DEG
    assert estimate.confidence <= elevation.WHEEL_CONFIDENCE_CEILING / 2


# ── The sensitivity finding, written as tests ──────────────────────────────────

def test_confidence_falls_as_the_elevation_falls():
    """
    Because theta = arccos(ratio), the uncertainty in degrees is sigma_ratio
    over sin(theta), so it blows up as the camera comes down. A flat per-rung
    confidence would let a downstream horizon shift trust a five-degree reading
    it cannot make, which is the whole reason confidence here is propagated from
    an error budget rather than asserted.
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
    """
    Above about 15 degrees sin(theta) is large enough that the inverse is well
    conditioned, so this is the band where a wrong constant or a sign slip in the
    chord relation would show as an offset rather than hide inside the noise.
    A raised phone is also the case that most damages a composite, so it is the
    one the module has to get right.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.degrees == pytest.approx(truth, abs=2.0)


@pytest.mark.parametrize("truth", [8.0, 11.16])
def test_a_middling_camera_is_recovered_loosely(truth):
    """
    Deliberately six degrees and not two. Writing a tight tolerance here would
    be writing a test that claims the module can do something the geometry says
    it cannot: at 11 degrees a one per cent error in the axis ratio moves the
    answer by three degrees, and a segmentation-derived tyre edge is worth about
    that. It would pass on these noiseless synthetics and fail on every real
    photograph, which is the worst kind of green.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.degrees == pytest.approx(truth, abs=6.0)


@pytest.mark.parametrize("truth", [3.0, 5.0])
def test_a_low_camera_is_not_claimed_to_be_measured(truth):
    """
    Below about 3.5 degrees the propagated one-sigma band covers the whole
    plausible range, and an estimate that wide is not a measurement. Nothing is
    asserted about the value here on purpose — only that whatever comes back
    arrives with a confidence low enough for a "shift only above X" policy to
    exclude it.
    """
    estimate = elevation.estimate_elevation(
        synthetic_cutout(truth, 0.0, pixels_per_metre=WHEEL_PPM), "side"
    )

    assert estimate.confidence < 0.25


def test_a_raised_camera_reads_higher_than_a_standing_or_crouching_one():
    """
    The strongest claim the analysis supports, and the one that stops a later
    change quietly reversing the sign of the relationship: this estimator can
    tell a genuinely high camera from a genuinely low one.

    What is deliberately NOT asserted is that crouching reads lower than
    standing. Those two are 6.5 degrees apart and separated by 1.6 percentage
    points of axis ratio, and across a range of render resolutions their
    recovered order flips — exactly as the sensitivity analysis in elevation.py
    predicts. Asserting it would be asserting a coincidence.
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
    """
    Pins the two vocabularies together without importing anything heavy —
    classification.py keeps torch inside its loader, so this costs nothing.
    `classification.ANGLES` is the only definition of the shot-angle terms, and
    an angle added there that this module has never seen must degrade to a lower
    rung rather than raise inside PipelineProcessor.process — which holds the
    cutout in exactly this shape, RGBA on transparency, between
    _apply_plate_treatment and _place_on_backdrop.
    """
    cutout = synthetic_cutout(11.16, 0.0)
    assert cutout.mode == "RGBA"

    for angle in (*classification.ANGLES, None):
        estimate = elevation.estimate_elevation(cutout, angle)
        assert estimate.method in elevation.ELEVATION_METHODS
        assert elevation.MIN_ELEVATION_DEG <= estimate.degrees <= elevation.MAX_ELEVATION_DEG
