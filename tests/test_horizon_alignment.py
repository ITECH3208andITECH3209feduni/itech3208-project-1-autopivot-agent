# Tests for Phase 1 — bringing a photograph's horizon and a backdrop's together.
#
# compositing.py and elevation.py import only cv2, numpy and PIL, so these run
# without a GPU and without a database:
#
#     pytest tests/test_horizon_alignment.py -v

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

import compositing
import elevation
import metrics


def car(width=600, height=260, colour=(180, 40, 40)):
    return Image.new("RGBA", (width, height), (*colour, 255))


def scene(width=1600, height=1200):
    """A backdrop the same shape as the canvas, which is what a dealer uploads."""
    return Image.new("RGBA", (width, height), (200, 200, 205, 255))


def gradient_scene(width=1600, height=1600):
    """
    A backdrop taller than the canvas, shaded down its height.

    Taller so there is slack to slide, and shaded so a test can tell one crop
    from another: a flat colour looks identical however it is cropped, which
    would let a shift that never happened pass.
    """
    column = np.linspace(0, 255, height, dtype=np.uint8)
    pixels = np.repeat(column[:, None], width, axis=1)
    rgba = np.dstack([pixels, pixels, pixels, np.full_like(pixels, 255)])
    return Image.fromarray(rgba, "RGBA")


# ── Standing on the dealer's own floor ─────────────────────────────────────────

def test_an_unmeasured_backdrop_composes_exactly_as_before():
    """
    The defect this exists to catch. A dealer who was happy with their listings
    must not see them move because a measurement was added for everyone else,
    so a backdrop with nothing measured has to return the preset that shipped.
    """
    assert compositing.dealer_preset() is compositing.DEALER_BACKDROP

    result, meta = compositing.compose(car(), scene(), compositing.dealer_preset())
    assert meta["vehicle_horizon_y_px"] is None
    assert meta["horizon_residual_px"] is None
    assert result.size == (1600, 1200)


def test_a_floor_that_starts_high_leaves_the_contact_line_alone():
    """
    The defect this exists to catch, and it shipped once. Deriving a standing
    position from the measured floor — 39% down it, as the studio scene does —
    lifted a car 133 pixels off the line it had been standing on quite happily,
    on a real dealer backdrop whose floor begins at 0.53. The studio has a raised
    platform in the middle distance and a dealer's showroom does not, and the
    compositor still draws the vehicle at 86% of the canvas width either way: a
    car both large and far back is what the eye reads as floating.

    So a floor beginning above the line that shipped changes nothing at all.
    """
    for floor_top in (0.30, 0.53, 0.60, 0.75):
        preset = compositing.dealer_preset(floor_top_y_ratio=floor_top)
        assert preset.ground_y_ratio == pytest.approx(
            compositing.DEALER_BACKDROP.ground_y_ratio
        ), f"a floor at {floor_top} must not move a car that was already on it"


@pytest.mark.parametrize("floor_top", [0.86, 0.90])
def test_a_floor_that_starts_low_moves_the_vehicle_down_onto_it(floor_top):
    """
    Gap 2 in the handover. A showroom whose floor begins below the assumed 84%
    line had its cars stood in the middle of the back wall, and that is the case
    a measurement has to correct.
    """
    preset = compositing.dealer_preset(floor_top_y_ratio=floor_top)

    assert preset.ground_y_ratio > floor_top, "the car must stand ON the floor"
    assert preset.ground_y_ratio > compositing.DEALER_BACKDROP.ground_y_ratio
    assert preset.ground_y_ratio <= compositing.MAX_GROUND_Y_RATIO, (
        "past this the contact line is at the frame edge and the car is cropped"
    )


def test_a_floor_with_almost_nothing_below_it_stops_at_the_frame_edge():
    """
    A backdrop that is nearly all wall cannot have a car stood below its
    junction without the car leaving the frame, so the cap wins and the vehicle
    stands slightly above the floor line. That is the least bad answer available
    and it is better stated here than discovered in a listing.
    """
    preset = compositing.dealer_preset(floor_top_y_ratio=0.97)

    assert preset.ground_y_ratio == pytest.approx(compositing.MAX_GROUND_Y_RATIO)
    assert preset.ground_y_ratio < 0.97, "the cap overrides the floor at this extreme"


def test_the_real_dealer_backdrop_keeps_the_line_that_shipped():
    """
    Measured from the showroom panorama that exposed this: its floor begins at
    0.528, comfortably above the 0.84 line, so the car stays exactly where it
    was and only the horizon work can move it.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.371, floor_top_y_ratio=0.528)
    assert preset.ground_y_ratio == pytest.approx(0.84)


# ── Where the photograph's horizon falls ───────────────────────────────────────

def test_a_higher_camera_puts_the_horizon_higher_up_the_frame():
    """
    The whole of Phase 1 rests on this being monotone. A photograph taken from
    overhead has its eye level further above the car than a crouching one does,
    and if the ordering were wrong every alignment would be backwards.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    horizons = [
        compositing.compose(car(), scene(), preset, elevation_deg=deg)[1][
            "vehicle_horizon_y_px"
        ]
        for deg in (
            elevation.CROUCHING_ELEVATION_DEG,
            elevation.STANDING_ELEVATION_DEG,
            elevation.RAISED_ELEVATION_DEG,
        )
    ]

    assert horizons == sorted(horizons, reverse=True), (
        "y grows downwards, so a raised camera must give a smaller y"
    )


def test_the_horizon_is_a_camera_height_rather_than_an_angle():
    """
    A horizon is a height above the ground seen at the car's distance, and the
    vehicle supplies the scale because it is a known number of metres rendered
    at a known number of pixels. Deriving it any other way would need a focal
    length the cutout no longer carries.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, meta = compositing.compose(
        car(), scene(), preset, elevation_deg=elevation.STANDING_ELEVATION_DEG
    )

    metres = elevation.camera_height_for_elevation(elevation.STANDING_ELEVATION_DEG)
    pixels_per_metre = meta["vehicle_height_px"] / elevation.REFERENCE_VEHICLE_HEIGHT_M
    expected = meta["contact_y_px"] - metres * pixels_per_metre

    assert meta["vehicle_horizon_y_px"] == pytest.approx(expected, abs=1.0)


# ── Moving the scene to meet it ────────────────────────────────────────────────

def test_the_scene_is_actually_shifted_not_merely_reported():
    """
    A metadata key saying the horizon was aligned is worth nothing if the
    pixels did not move. Two elevations must crop the backdrop differently.
    """
    preset = replace(
        compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60),
        output_size=(1600, 1200),
    )
    low, _ = compositing.compose(
        car(), gradient_scene(1600, 2000), preset,
        elevation_deg=elevation.CROUCHING_ELEVATION_DEG,
    )
    high, _ = compositing.compose(
        car(), gradient_scene(1600, 2000), preset,
        elevation_deg=elevation.RAISED_ELEVATION_DEG,
    )

    # The top-left corner is backdrop in both, well away from the vehicle.
    assert low.getpixel((5, 5)) != high.getpixel((5, 5))


def test_a_scene_larger_than_its_canvas_aligns_fully():
    """
    Given genuine slack the alignment is exact, which is what proves the
    clamping in the next test is a property of the backdrop's shape rather than
    a limit of the mechanism.

    The slack has to come from a preset with a fixed output size. A dealer's
    backdrop has none — see the test below for why that matters.
    """
    preset = replace(
        compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60),
        output_size=(1600, 1200),
    )
    _, meta = compositing.compose(
        car(), gradient_scene(1600, 2000), preset,
        elevation_deg=elevation.STANDING_ELEVATION_DEG,
    )

    assert meta["horizon_residual_px"] == pytest.approx(0.0, abs=1.5)


def test_a_dealer_backdrop_can_only_be_aligned_within_the_overscale_budget():
    """
    Worth stating outright, because it decides what Phase 1 can promise. A
    dealer backdrop is composed at its own resolution — `_canvas_size` returns
    the backdrop's dimensions when a preset carries no output_size — so the
    scene exactly covers the canvas and has no spare pixels to slide. Every bit
    of movement therefore comes from enlarging, which is capped, and a
    photograph taken from far from the backdrop's own camera height cannot be
    fully aligned by cropping at all.

    That is not a defect to fix here: it is the measurement that says which
    camera heights the room should be re-rendered at, which is the backdrop
    variant work REALISM_PLAN.md describes.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    residuals = [
        compositing.compose(car(), scene(), preset, elevation_deg=deg)[1][
            "horizon_residual_px"
        ]
        for deg in (
            elevation.CROUCHING_ELEVATION_DEG,
            elevation.STANDING_ELEVATION_DEG,
            elevation.RAISED_ELEVATION_DEG,
        )
    ]

    # Ordered, because a higher camera needs the scene shifted further the other
    # way, and at least one end clamped, because the budget cannot cover the
    # whole range a dealer shoots over.
    assert residuals == sorted(residuals)
    assert max(abs(r) for r in residuals) > 20.0


def test_a_shortfall_is_reported_rather_than_hidden():
    """
    A backdrop exactly the shape of the canvas has nothing spare, and enlarging
    it is capped. REALISM_PLAN.md says as much — shifting a crop only goes so
    far before the room needs re-rendering at the right camera height — so the
    residual has to be visible, because it is the number that says a re-render
    would help.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, meta = compositing.compose(
        car(), scene(), preset, elevation_deg=elevation.CROUCHING_ELEVATION_DEG
    )

    assert meta["horizon_residual_px"] is not None
    assert abs(meta["horizon_residual_px"]) > 1.0


def test_alignment_needs_both_halves():
    """
    A measured backdrop with no elevation, or an elevation with an unmeasured
    backdrop, leaves nothing to align against. Either alone must compose as
    before rather than sliding the scene against a guess.
    """
    measured = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, without_elevation = compositing.compose(car(), scene(), measured)
    _, without_horizon = compositing.compose(
        car(), scene(), compositing.dealer_preset(floor_top_y_ratio=0.60),
        elevation_deg=elevation.STANDING_ELEVATION_DEG,
    )

    assert without_elevation["horizon_residual_px"] is None
    assert without_horizon["horizon_residual_px"] is None


def test_the_scene_is_never_enlarged_beyond_the_cap():
    """
    Enlarging crops into a dealer's scene and costs them field of view they
    chose to include, so an unreachable alignment has to be given up on rather
    than chased.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.05, floor_top_y_ratio=0.60)
    fitted, _ = compositing._fit_backdrop(scene(), (1600, 1200), 0.05, 1100.0)

    assert fitted.size == (1600, 1200)


# ── Which estimates are allowed to move a dealer's room ────────────────────────

def test_only_the_rungs_that_read_the_photograph_count_as_measured():
    """
    The defect this exists to catch, and it is a subtle one. A confidence floor
    is not enough to keep a population prior out: 'shot_angle' returns 11.16 deg
    for every side-on photograph ever taken, at a confidence of 0.20 that clears
    any sensible floor. Gating horizon alignment on confidence alone would slide
    a dealer's backdrop by a fact about dealers in general, while looking
    exactly like a measurement of their car.
    """
    assert set(elevation.MEASURED_METHODS) == {"wheel_ellipse", "roof_underside"}

    for prior in ("shot_angle", "assumed"):
        assert prior in elevation.ELEVATION_METHODS, "still part of the cascade"
        assert prior not in elevation.MEASURED_METHODS, "but never an observation"

    # The prior's own confidence really does clear the floor, which is why the
    # method test has to exist rather than a stricter threshold being enough.
    assert elevation.ANGLE_PRIOR_CONFIDENCE_NAMED > elevation.MIN_USEFUL_CONFIDENCE


def test_the_harness_and_the_compositor_agree_on_what_measured_means():
    """
    Two copies of this distinction would eventually disagree, and then the
    evidence a phase is judged on would be counting rows the compositor had
    declined to act on.
    """
    from scripts import realism_report

    assert realism_report.MEASURED_ELEVATION_METHODS == elevation.MEASURED_METHODS


# ── The measure Phase 1 is judged on ───────────────────────────────────────────

def test_the_horizon_offset_metric_now_has_both_of_its_inputs():
    """
    metrics.horizon_offset shipped in Stage 0 with neither end wired: no preset
    carried a horizon and nothing estimated a photograph's. Both now exist, so
    the measure Phase 1 is judged on can finally be taken.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, meta = compositing.compose(
        car(), scene(), preset, elevation_deg=elevation.STANDING_ELEVATION_DEG
    )

    offset = metrics.horizon_offset(
        vehicle_horizon_ratio=meta["vehicle_horizon_y_px"] / meta["output_size"]["height"],
        backdrop_horizon_ratio=preset.horizon_y_ratio,
        canvas_height=meta["output_size"]["height"],
    )

    assert isinstance(offset, float)
