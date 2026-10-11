# Tests for turning an estimated camera elevation into a camera height, at the
# bottom of the range the estimator can report.
#
# elevation.py and compositing.py import only cv2, numpy and PIL, so these run
# without a GPU and without a database:
#
#     pytest tests/test_elevation_bounds.py -v
#
# The defect: the estimator measures an ANGLE, down to MIN_ELEVATION_DEG = -5,
# and the compositor needs a HEIGHT, which it gets as 0.316 m + 6 m * tan(angle)
# at the one shooting distance the module assumes. Below atan(-0.316 / 6), about
# -3.01 degrees, that height is negative: a camera under the floor. The angle
# itself is not wrong — a phone on the ground closer than six metres really does
# look up at the wheel centres that steeply — but the height it converts to is,
# and the compositor then put the photograph's horizon below the car's tyres and
# slid the dealer's backdrop down after it.

import math

import pytest
from PIL import Image, ImageDraw

import compositing
import elevation


def car():
    return Image.new("RGBA", (600, 260), (180, 40, 40, 255))


def showroom():
    return Image.new("RGBA", (1600, 1200), (200, 200, 205, 255))


def tall_vehicle_end_on(gap_ratio=0.215, width=360, height=400):
    """
    A high-riding vehicle seen head-on from low down: a body over two tyres,
    with daylight under the body for `gap_ratio` of the silhouette's height.

    The underside rung reads that gap against a 0.25 m valance on a 1.45 m car.
    A lifted four-wheel drive or a ute shows a good deal more of it, and past
    about a fifth of its height the rung reports an elevation below -3.01.
    """
    image = Image.new("RGBA", (width + 40, height + 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    paint = (176, 62, 58, 255)
    body_bottom = 20 + round(height * (1 - gap_ratio))
    draw.rectangle((20, 20, 20 + width - 1, body_bottom - 1), fill=paint)
    tyre = round(width * 0.16)
    for left in (20, 20 + width - tyre):
        draw.rectangle((left, body_bottom - 40, left + tyre - 1, 20 + height - 1), fill=paint)
    return image


# The elevation at which a camera six metres from the car would be on the
# ground, worked out here rather than taken from the module: atan(-0.316 / 6).
GROUND_LEVEL_DEG = math.degrees(math.atan2(-0.316, 6.0))


@pytest.mark.parametrize("degrees", [elevation.MIN_ELEVATION_DEG, -4.0, -3.5, -3.02])
def test_no_elevation_the_estimator_can_report_puts_the_camera_below_the_ground(degrees):
    """
    The defect this exists to catch: -5 degrees, which the estimator reports
    and the database accepts, converted to a camera 0.21 m under the floor.
    """
    assert elevation.camera_height_for_elevation(degrees) >= 0.0


@pytest.mark.parametrize(
    "degrees, metres",
    [
        (elevation.RAISED_ELEVATION_DEG, 2.20),
        (elevation.STANDING_ELEVATION_DEG, 1.50),
        (elevation.CROUCHING_ELEVATION_DEG, 0.80),
        (0.0, 0.316),
        # A photographer kneeling with the phone below the wheel centres: a
        # genuinely negative angle, and a camera that is still above the floor.
        (-1.0, 0.211),
        (-3.0, 0.0016),
    ],
)
def test_every_height_a_camera_can_actually_have_is_left_alone(degrees, metres):
    """
    The fix to guard. Bounding the conversion at the floor must not move any
    camera that was above it, and in particular must not throw away the
    negative angles a low camera genuinely produces by clamping the angle at
    zero instead.
    """
    assert elevation.camera_height_for_elevation(degrees) == pytest.approx(metres, abs=0.001)


@pytest.mark.parametrize("degrees", [elevation.MIN_ELEVATION_DEG, -4.0])
def test_the_photographs_horizon_never_falls_below_the_car_standing_in_it(degrees):
    """
    A horizon is the camera's own height, so the lowest it can be is the ground
    the car stands on. At -5 degrees it was put 52 pixels below this car's
    tyres, and a dealer's backdrop was enlarged and slid down to meet it.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, meta = compositing.compose(car(), showroom(), preset, elevation_deg=degrees)

    assert meta["vehicle_horizon_y_px"] <= meta["contact_y_px"]


def test_a_tall_vehicle_seen_end_on_does_not_drag_the_horizon_under_its_tyres():
    """
    The same defect the way a listing meets it. Nothing about it is exotic: the
    underside rung answers end-on at its full 0.35 confidence, well clear of
    the floor the pipeline gates alignment on, and it is a measurement rather
    than a prior, so autopivot_backend._place_on_backdrop hands the angle
    straight to compose().
    """
    photograph = tall_vehicle_end_on()
    estimate = elevation.estimate_elevation(photograph, "front")

    # What makes this photograph the case in point. The gate is the one
    # autopivot_backend._place_on_backdrop applies before composing, which
    # cannot be imported here without torch.
    assert estimate.method in elevation.MEASURED_METHODS
    assert estimate.confidence >= elevation.MIN_USEFUL_CONFIDENCE
    assert estimate.degrees < GROUND_LEVEL_DEG, (
        f"{estimate.degrees:.2f} degrees is a camera above the ground, so this "
        "photograph no longer exercises the bound"
    )

    preset = compositing.dealer_preset(horizon_y_ratio=0.45, floor_top_y_ratio=0.60)
    _, meta = compositing.compose(
        photograph, showroom(), preset, angle="front", elevation_deg=estimate.degrees
    )

    assert meta["vehicle_horizon_y_px"] <= meta["contact_y_px"]
    # And what is recorded is still the angle that was measured.
    assert meta["camera_elevation_deg"] == estimate.degrees
