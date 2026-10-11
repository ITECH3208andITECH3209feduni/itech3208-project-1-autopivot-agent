# A plate the edge of the photograph cuts through must still be obscured.
#
# YOLOS does not keep its boxes inside the image. It predicts a centre and a
# size, and transformers scales those to pixels without clamping them
# (YolosImageProcessor.post_process_object_detection), so a plate at the very
# edge of the frame comes back with xmin=-5. The coverage check sliced the
# cutout's alpha with the box as given, and NumPy reads a negative start as
# counting back from the far end: alpha[:, -5:129] on a 518-pixel crop is
# alpha[:, 513:129], which is empty. Coverage came out 0, and a plate sitting on
# the vehicle was thrown away as if it had been found in empty space — and left
# readable.
#
# It happens whenever the photograph cuts the vehicle off. The crop pads the
# vehicle box by 8%, but it cannot pad past the edge of the photograph, so a
# bumper at the edge of the photo is at the edge of the crop too.
#
# These import autopivot_backend, which needs the ML environment
# (requirements-ml.txt). No model is downloaded: the plate detector is the real
# transformers pipeline around a tiny YOLOS built on the spot, and the other
# models are replaced.
#
#     pytest tests/test_plate_frame_edge.py -v

import io

import numpy as np
import pytest
from PIL import Image

import autopivot_backend as backend
from test_plate_detection_threshold import yolos_pipeline


WIDTH, HEIGHT = 400, 300
VEHICLE_AREA = 100_000.0


def plate(xmin, ymin, xmax, ymax, score=0.9):
    return {
        "score": score,
        "box": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
    }


def opaque():
    """A cutout where every pixel belongs to the vehicle."""
    return Image.new("RGBA", (WIDTH, HEIGHT), (128, 128, 128, 255))


# Each box is 140x50 — an AU/NZ plate square on — run 3 to 10 pixels past one
# edge of a 400x300 crop, the way YOLOS reports a plate the frame cuts through.
AT_THE_EDGE = {
    "left": (-4, 120, 136, 170),
    "top": (130, -3, 270, 47),
    "right": (270, 120, 410, 170),
    "bottom": (130, 255, 270, 305),
}


@pytest.mark.parametrize("edge", AT_THE_EDGE)
def test_a_plate_the_frame_cuts_through_is_kept(edge):
    kept = backend._filter_plates([plate(*AT_THE_EDGE[edge])], VEHICLE_AREA, opaque())
    assert len(kept) == 1


def test_a_plate_the_frame_cuts_in_half_is_kept_though_what_is_left_is_square():
    """
    A 2:1 plate centred on the left edge: half of it is in the photograph, and
    that half is 50x50. Shape is judged on the box the detector reported, not on
    what survives the frame — a square is nothing like a plate, and those 50
    columns can still carry a readable half of the registration.
    """
    kept = backend._filter_plates([plate(-50, 120, 50, 170)], VEHICLE_AREA, opaque())
    assert kept == [
        {"score": 0.9, "box": {"xmin": 0, "ymin": 120, "xmax": 50, "ymax": 170}}
    ]


@pytest.mark.parametrize("edge, inside", [
    ("left", {"xmin": 0, "ymin": 120, "xmax": 136, "ymax": 170}),
    ("top", {"xmin": 130, "ymin": 0, "xmax": 270, "ymax": 47}),
    ("right", {"xmin": 270, "ymin": 120, "xmax": 400, "ymax": 170}),
    ("bottom", {"xmin": 130, "ymin": 255, "xmax": 270, "ymax": 300}),
])
def test_a_kept_plate_is_handed_on_as_the_part_inside_the_frame(edge, inside):
    """
    What leaves the filter goes to the treatment, and the part of the plate in
    the photograph is the part there is to obscure. Handing on the detector's
    own numbers would leave every consumer one slice away from the wraparound
    the coverage check fell into.
    """
    kept = backend._filter_plates([plate(*AT_THE_EDGE[edge])], VEHICLE_AREA, opaque())
    assert kept == [{"score": 0.9, "box": inside}]


def test_coverage_is_measured_on_the_part_of_the_box_inside_the_frame():
    """
    The pixels beyond the edge are neither vehicle nor background: they are not
    in the photograph at all, so they count for nothing either way. Only the
    first 60 columns of this cutout are vehicle. The box runs from -20 to 120,
    so 120 of its columns are in the frame and 60 of those are on the vehicle.
    """
    cutout = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    cutout.paste((128, 128, 128, 255), (0, 0, 60, HEIGHT))

    assert backend._plate_coverage(cutout, (-20, 100, 120, 150)) == 0.5


# ── Through the pipeline ──────────────────────────────────────────────────────

PHOTO_SIZE = (640, 480)
# Starts at the left edge of the photograph, so the crop's padding cannot extend
# past it: the crop is (0, 96)-(518, 444).
VEHICLE_BOX = {"xmin": 0, "ymin": 120, "xmax": 480, "ymax": 420}
# What the tiny YOLOS below reports on that 518x348 crop, as measured:
# {'xmin': -5, 'ymin': 226, 'xmax': 129, 'ymax': 261}. In the photograph that is
# (-5, 322)-(129, 357), of which columns 0 to 129 are in the frame.
PLATE_IN_PHOTO = (0, 322, 129, 357)


def photograph_with_a_plate_at_the_edge() -> Image.Image:
    """Hard vertical stripes stand in for the characters on the plate."""
    pixels = np.full((PHOTO_SIZE[1], PHOTO_SIZE[0], 3), 90, dtype=np.uint8)
    x1, y1, x2, y2 = PLATE_IN_PHOTO
    pixels[y1:y2, x1:x2] = 0
    pixels[y1:y2, x1:x2:4] = 255
    return Image.fromarray(pixels)


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_plate_the_frame_cuts_through_comes_out_of_the_pipeline_obscured(monkeypatch):
    photo = photograph_with_a_plate_at_the_edge()

    monkeypatch.setattr(backend, "_classify", lambda image: None)
    monkeypatch.setattr(
        backend,
        "_detect_vehicle",
        lambda image: {"class": "car", "score": 0.95, "box": dict(VEHICLE_BOX)},
    )
    # The vehicle fills the crop, so the whole plate is on the cutout.
    monkeypatch.setattr(
        backend, "_remove_background", lambda crop: (crop.convert("RGBA"), "stub")
    )
    monkeypatch.setattr(backend, "_estimate_elevation", lambda cutout, angle: None)
    monkeypatch.setattr(
        backend.registry,
        "_plates",
        yolos_pipeline(score=0.9, centre=(0.12, 0.7), size=(0.26, 0.1)),
    )
    monkeypatch.setattr(backend.registry, "_plates_ok", True)

    outcome = backend.PipelineProcessor().process(png(photo), None)

    x1, y1, x2, y2 = PLATE_IN_PHOTO
    before = np.array(photo)[y1:y2, x1:x2].astype(float)
    after = np.array(Image.open(io.BytesIO(outcome.image_png)).convert("RGB"))[
        y1:y2, x1:x2
    ].astype(float)
    # The stripes swing the full 0-255. Anything close to that is still legible.
    assert after.std() < before.std() / 3
    assert outcome.plates_detected == 1
