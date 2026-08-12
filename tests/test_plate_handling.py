# Tests for licence-plate filtering and obscuration.
#
# These import autopivot_backend, which loads torch and ultralytics at module
# level, so they need the ML environment (requirements-ml.txt) — a GPU is not
# required and no model is downloaded, because nothing here touches the
# detectors themselves.
#
#     pytest tests/test_plate_handling.py -v

import numpy as np
import pytest
from PIL import Image

import autopivot_backend as backend


def plate(xmin, ymin, xmax, ymax, score=0.9):
    return {
        "score": score,
        "box": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
    }


def opaque(width=400, height=300):
    """A cutout where every pixel belongs to the vehicle."""
    return Image.new("RGBA", (width, height), (128, 128, 128, 255))


def cutout_with_hole(box, width=400, height=300):
    """Opaque everywhere except `box`, which is fully transparent."""
    image = opaque(width, height)
    x1, y1, x2, y2 = box
    image.paste((0, 0, 0, 0), (x1, y1, x2, y2))
    return image


# ── Shape ──────────────────────────────────────────────────────────────────────

def test_plate_shaped_box_is_kept():
    # 140×50 is 2.8:1 — an AU/NZ plate seen square on.
    kept = backend._filter_plates([plate(10, 10, 150, 60)], 100_000.0, opaque())
    assert len(kept) == 1


@pytest.mark.parametrize("box", [
    (10, 10, 60, 60),     # square, 1:1
    (10, 10, 40, 200),    # taller than wide
    (10, 10, 400, 20),    # 39:1 letterbox
])
def test_boxes_that_are_not_plate_shaped_are_rejected(box):
    assert backend._filter_plates([plate(*box)], 100_000.0, opaque()) == []


# ── Size relative to the vehicle ───────────────────────────────────────────────

def test_box_covering_most_of_the_vehicle_is_rejected():
    # Correct aspect, but 40% of the vehicle — a windscreen or a flank, not a
    # plate. 280x100 = 28,000 against a 70,000 px vehicle.
    assert backend._filter_plates([plate(0, 0, 280, 100)], 70_000.0, opaque()) == []


def test_area_check_is_skipped_when_no_vehicle_area_is_known():
    # /detect-and-hide has no vehicle box; passing 0.0 must not reject.
    kept = backend._filter_plates([plate(0, 0, 280, 100)], 0.0, None)
    assert len(kept) == 1


# ── Coverage: the regression this was built for ────────────────────────────────

def test_plate_detected_off_the_vehicle_is_rejected():
    """
    The photo-3 defect: the detector fires on background, and the old code
    painted a white rectangle into empty space. The box is plate-shaped and
    plate-sized, so only cutout coverage can catch it.
    """
    floating = (200, 200, 340, 250)
    cutout = cutout_with_hole(floating)
    assert backend._filter_plates([plate(*floating)], 100_000.0, cutout) == []


def test_plate_on_the_vehicle_survives():
    cutout = cutout_with_hole((0, 0, 20, 20))  # transparent corner, far away
    kept = backend._filter_plates([plate(200, 200, 340, 250)], 100_000.0, cutout)
    assert len(kept) == 1


def test_plate_half_off_the_vehicle_is_rejected_at_default_threshold():
    # Straddles the edge: 50% coverage against a 55% requirement.
    cutout = cutout_with_hole((270, 200, 340, 250))
    assert backend._filter_plates([plate(200, 200, 340, 250)], 100_000.0, cutout) == []


def test_coverage_is_measured_as_a_fraction():
    cutout = cutout_with_hole((100, 100, 200, 200))
    assert backend._plate_coverage(cutout, (100, 100, 200, 200)) == 0.0
    assert backend._plate_coverage(cutout, (0, 0, 50, 50)) == 1.0


# ── Obscuration ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["blur", "pixelate", "white"])
def test_obscuration_destroys_the_characters(monkeypatch, mode):
    monkeypatch.setattr(backend, "PLATE_TREATMENT", mode)

    # Hard vertical stripes stand in for plate characters. If any survive,
    # the region is still readable.
    region = np.zeros((50, 140, 3), dtype=np.uint8)
    region[:, ::4] = 255

    result = backend._obscure_region(region)

    assert result.shape == region.shape
    # Original stripes swing the full 0–255. Anything close to that means
    # detail survived.
    assert result.std() < region.std() / 3


def test_obscuration_handles_a_region_narrower_than_the_mosaic_width():
    region = np.full((4, 3, 3), 200, dtype=np.uint8)
    assert backend._obscure_region(region).shape == region.shape


def test_treatment_leaves_alpha_untouched():
    """
    The white-rectangle version forced alpha to 255 across the box, so a stray
    detection punched an opaque block into the transparent background and
    survived compositing onto the backdrop.
    """
    image = Image.new("RGBA", (200, 200), (10, 20, 30, 0))  # fully transparent
    treated = backend._apply_plate_treatment(image, [plate(50, 50, 190, 100)], None)

    alpha = np.array(treated.getchannel("A"))
    assert alpha.max() == 0, "treatment must not make transparent pixels opaque"


def test_overlay_path_still_composites():
    image = Image.new("RGBA", (200, 200), (10, 20, 30, 255))
    overlay = Image.new("RGBA", (60, 20), (255, 0, 0, 255))

    treated = backend._apply_plate_treatment(image, [plate(50, 50, 190, 100)], overlay)
    centre = treated.getpixel((120, 75))

    assert centre[:3] == (255, 0, 0)


# ── Confidence threshold ───────────────────────────────────────────────────────

def test_box_area_is_clamped_at_zero():
    assert backend._box_area({"xmin": 10, "ymin": 10, "xmax": 5, "ymax": 5}) == 0.0
    assert backend._box_area({"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 4}) == 40.0
