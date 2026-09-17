# Tests for the whole-car-in-frame check.
#
# These import autopivot_backend, which loads torch and ultralytics at module
# level, so they need the ML environment (requirements-ml.txt) — a GPU is not
# required and no model is downloaded, because nothing here touches the
# detectors themselves.
#
#     pytest tests/test_framing.py -v

import autopivot_backend as backend


def box(xmin, ymin, xmax, ymax):
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


# A 1000x800 photograph throughout. The check is pixel-based (see
# _FRAME_EDGE_MARGIN_PX), not a fraction of these dimensions, so the size
# itself is arbitrary — kept only for readable box coordinates.
SIZE = (1000, 800)


def test_a_comfortably_framed_car_is_not_cropped():
    # Generous margin on every side.
    assert not backend._vehicle_is_cropped_by_frame(box(80, 120, 900, 700), SIZE)


def test_a_box_touching_the_left_edge_is_cropped():
    assert backend._vehicle_is_cropped_by_frame(box(0, 120, 700, 700), SIZE)


def test_a_box_touching_the_right_edge_is_cropped():
    assert backend._vehicle_is_cropped_by_frame(box(80, 120, 1000, 700), SIZE)


def test_a_box_touching_the_top_edge_is_cropped():
    assert backend._vehicle_is_cropped_by_frame(box(80, 0, 900, 700), SIZE)


def test_a_box_touching_the_bottom_edge_is_cropped():
    assert backend._vehicle_is_cropped_by_frame(box(80, 120, 900, 800), SIZE)


def test_a_box_a_few_pixels_short_of_the_edge_is_not_cropped():
    # Just outside the 2px tolerance on every side — a real, if modest,
    # margin, not a box clipped to the boundary.
    assert not backend._vehicle_is_cropped_by_frame(box(3, 3, 997, 797), SIZE)


def test_a_box_within_the_rounding_tolerance_of_the_edge_is_cropped():
    # Within the couple of pixels this allows for float rounding on a box
    # ultralytics has already clipped to the frame.
    assert backend._vehicle_is_cropped_by_frame(box(2, 120, 900, 700), SIZE)


def test_a_modest_real_world_margin_is_not_cropped():
    """
    The regression this was rewritten for: a genuine, whole-car dealer photo
    reported as "needs a person" because the old check measured margin as a
    fraction of the frame (1.5%) rather than in pixels. On a decent-sized
    photograph, 1.5% is dozens of pixels — comfortably more headroom than
    plenty of real, well-composed shots leave on their tightest side — so it
    was flagging ordinary photographs, not cropped ones.

    A 1200x900 photograph with the old 1.5% check: margins of 18px and 13.5px.
    A box sitting 10px off the bottom (890 of 900) tripped the old check
    (890 >= 900 - 13.5) despite being a completely ordinary composition.
    """
    ordinary_size = (1200, 900)
    assert not backend._vehicle_is_cropped_by_frame(
        box(40, 30, 1150, 890), ordinary_size
    )


def test_a_zero_sized_photograph_is_not_treated_as_cropped():
    """Defensive: nothing here should ever raise on a degenerate image size."""
    assert not backend._vehicle_is_cropped_by_frame(box(0, 0, 10, 10), (0, 0))
