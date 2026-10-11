# Tests for Phase 1 horizon alignment keeping the vehicle on a dealer's floor.
#
# compositing.py imports only cv2, numpy and PIL, so these run without a GPU and
# without a database:
#
#     pytest tests/test_alignment_floor.py -v
#
# The defect: `dealer_preset` stands a car on the measured floor using the
# floor's position in the backdrop as uploaded, and horizon alignment then
# slides and enlarges that backdrop — which carries the floor down the frame
# with the horizon. Nothing looked at the floor again, so a showroom whose floor
# starts low had its cars stood in the back wall as soon as a photograph's
# horizon asked for the scene to move down.
#
# Where the floor ends up is read off the finished frame rather than recomputed
# with the compositor's own arithmetic: the backdrop is two flat tones, wall
# above the measured junction and floor below it, and its left edge is far
# enough from the car that no shadow reaches it.

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

import compositing
import elevation

WIDTH, HEIGHT = 1600, 1200
HORIZON = 0.45

WALL = (200, 200, 205)
FLOOR = (90, 70, 50)
# Two rows of this across the wall mark where the scene's own horizon is, so
# the frame can say where it went.
MARKER = (20, 160, 20)


def showroom(floor_top, width=WIDTH, height=HEIGHT, horizon=HORIZON):
    """A backdrop the shape of the canvas, as a dealer uploads one."""
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    junction = round(floor_top * height)
    rgba[:junction, :, :3] = WALL
    rgba[junction:, :, :3] = FLOOR
    # Rows 539 and 540 span [539, 541): centred on 0.45 * 1200 = 540.
    centre = round(horizon * height)
    rgba[centre - 1:centre + 1, :, :3] = MARKER
    return Image.fromarray(rgba, "RGBA")


def car():
    return Image.new("RGBA", (600, 260), (180, 40, 40, 255))


def floor_starts_at(frame):
    """The first row of floor in the finished frame, or its height if none shows."""
    column = np.asarray(frame.convert("RGB"))[:, 5, :].astype(int)
    floor = np.flatnonzero(np.abs(column - FLOOR).sum(axis=1) < 30)
    return int(floor[0]) if floor.size else frame.height


def tyres_at(frame):
    """The lowest row of the car's paint, which is where it stands."""
    pixels = np.asarray(frame.convert("RGB"))
    paint = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    return int(np.flatnonzero(paint.any(axis=1))[-1])


def horizon_at(frame):
    """Where the marker landed, as the centroid of its rows in canvas pixels."""
    column = np.asarray(frame.convert("RGB"))[:, 5, :].astype(float)
    # How green each row is against the wall it was drawn on.
    weight = np.clip(column[:, 1] - column[:, 0] - 5.0, 0.0, None)
    rows = np.arange(frame.height) + 0.5
    return float((rows * weight).sum() / weight.sum())


@pytest.mark.parametrize("floor_top", [0.80, 0.88])
@pytest.mark.parametrize(
    "camera",
    [elevation.CROUCHING_ELEVATION_DEG, elevation.STANDING_ELEVATION_DEG],
    ids=["crouching", "standing"],
)
def test_aligning_the_horizon_never_stands_the_car_in_the_wall(floor_top, camera):
    """
    The defect this exists to catch. A 1600x1200 showroom with its horizon at
    0.45 and its floor starting at 0.88 has the car stood at 1065, on the
    floor. A standing photograph's horizon then wants the scene 150 pixels
    further down; the scene is enlarged by the full ten per cent with its crop
    pinned to the top edge, and the junction goes from 1056 to 1162 — the car's
    tyres 97 pixels up the back wall. A floor at 0.80 loses 48 pixels the same
    way, and anything past about 0.764 is affected.

    Standing on the floor is the one thing a composite cannot get wrong and
    still read as a photograph, and horizon alignment is best effort by design:
    it already stops short at the enlargement budget and says so in the
    residual. So the floor limits the alignment, not the other way round.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=HORIZON, floor_top_y_ratio=floor_top)

    # The control: before anything is aligned the dealer rule has the car on
    # its floor, so whatever takes it off is the alignment's doing.
    level, _ = compositing.compose(car(), showroom(floor_top), preset)
    assert tyres_at(level) > floor_starts_at(level)

    frame, meta = compositing.compose(
        car(), showroom(floor_top), preset, elevation_deg=camera
    )
    assert meta["horizon_residual_px"] is not None, "the alignment has to have run"

    junction = floor_starts_at(frame)
    assert tyres_at(frame) > junction, (
        f"the tyres stand at row {tyres_at(frame)}, above a floor that starts at {junction}"
    )
    # On the floor by the margin the dealer rule gives every car, rather than
    # pressed against the foot of the wall.
    assert meta["contact_y_px"] >= (
        junction + compositing.FLOOR_CONTACT_MARGIN * (HEIGHT - junction) - 2
    )


def test_a_scene_with_room_to_slide_is_not_slid_off_its_floor():
    """
    The same defect with no enlargement at all. A backdrop taller than its
    canvas has slack, so a crouching photograph's horizon is met in full just
    by cropping further up the scene — and on this 1600x2000 showroom with its
    floor at 0.60 that put the junction at row 1109 of 1200, with the car on
    its 1008 line a hundred pixels up the wall. The crop has to stop where the
    floor still reaches the car.
    """
    preset = replace(
        compositing.dealer_preset(horizon_y_ratio=HORIZON, floor_top_y_ratio=0.60),
        output_size=(WIDTH, HEIGHT),
    )
    frame, meta = compositing.compose(
        car(), showroom(0.60, height=2000), preset,
        elevation_deg=elevation.CROUCHING_ELEVATION_DEG,
    )

    junction = floor_starts_at(frame)
    assert tyres_at(frame) > junction, (
        f"the tyres stand at row {tyres_at(frame)}, above a floor that starts at {junction}"
    )
    assert meta["contact_y_px"] >= (
        junction + compositing.FLOOR_CONTACT_MARGIN * (HEIGHT - junction) - 2
    )


def test_a_floor_that_is_already_short_is_not_pushed_out_of_the_frame():
    """
    A backdrop that is nearly all wall already has its car above the junction
    — the MAX_GROUND_Y_RATIO cap keeps the car in the frame, as
    test_horizon_alignment records — and that is the least bad answer on offer.
    Alignment must not make it worse: enlarging this scene by ten per cent with
    the crop pinned to the top pushed its floor off the bottom of the canvas
    altogether, leaving a car standing against nothing but wall.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=HORIZON, floor_top_y_ratio=0.97)

    level, _ = compositing.compose(car(), showroom(0.97), preset)
    aligned, _ = compositing.compose(
        car(), showroom(0.97), preset, elevation_deg=elevation.STANDING_ELEVATION_DEG
    )

    assert floor_starts_at(level) < HEIGHT, "the unaligned scene shows its floor"
    assert floor_starts_at(aligned) <= floor_starts_at(level) + 1


def test_the_floor_limits_the_alignment_rather_than_cancelling_it():
    """
    The fix to guard. Refusing to align any backdrop whose floor is measured
    would pass the tests above and throw Phase 1 away for every dealer: a floor
    at 0.80 leaves room to slide the scene part of the way towards a standing
    photograph's horizon, and that part has to be taken.

    And the residual has to stay honest when the floor is what stopped the
    alignment, because it is the number that says a re-render would help: it
    must be the distance to where the scene's horizon really is in the frame.
    """
    preset = compositing.dealer_preset(horizon_y_ratio=HORIZON, floor_top_y_ratio=0.80)
    frame, meta = compositing.compose(
        car(), showroom(0.80), preset, elevation_deg=elevation.STANDING_ELEVATION_DEG
    )

    wanted = meta["vehicle_horizon_y_px"]
    left_alone = HORIZON * HEIGHT - wanted  # the residual with no alignment at all
    assert abs(meta["horizon_residual_px"]) < abs(left_alone) - 5.0

    assert horizon_at(frame) == pytest.approx(wanted + meta["horizon_residual_px"], abs=1.5)
