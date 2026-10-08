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
    assert backend._filter_plates([plate(0, 0, 280, 100)], 70_000.0, opaque()) == []


def test_area_check_is_skipped_when_no_vehicle_area_is_known():
    kept = backend._filter_plates([plate(0, 0, 280, 100)], 0.0, None)
    assert len(kept) == 1


# ── Coverage: the regression this was built for ────────────────────────────────

def test_plate_detected_off_the_vehicle_is_rejected():
    """The photo-3 defect: the detector fires on background, and the old code painted a
    white rectangle into empty space.
    """
    floating = (200, 200, 340, 250)
    cutout = cutout_with_hole(floating)
    assert backend._filter_plates([plate(*floating)], 100_000.0, cutout) == []


def test_plate_on_the_vehicle_survives():
    cutout = cutout_with_hole((0, 0, 20, 20))  # transparent corner, far away
    kept = backend._filter_plates([plate(200, 200, 340, 250)], 100_000.0, cutout)
    assert len(kept) == 1


def test_plate_half_off_the_vehicle_is_rejected_at_default_threshold():
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

    region = np.zeros((50, 140, 3), dtype=np.uint8)
    region[:, ::4] = 255

    result = backend._obscure_region(region)

    assert result.shape == region.shape
    assert result.std() < region.std() / 3


def test_obscuration_handles_a_region_narrower_than_the_mosaic_width():
    region = np.full((4, 3, 3), 200, dtype=np.uint8)
    assert backend._obscure_region(region).shape == region.shape


def test_treatment_leaves_alpha_untouched():
    """The white-rectangle version forced alpha to 255 across the box, so a stray
    detection punched an opaque block into the transparent background and survived
    compositing onto the backdrop.
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


def test_even_a_confident_side_label_does_not_switch_plate_masking_off():
    """A rear-quarter Ford Escape went out with its plate readable. The angle classifier
    is no longer trusted to turn plate masking off at all.
    """
    kept = backend._filter_plates(
        [plate(10, 10, 150, 60)], 100_000.0, opaque(), angle="side", angle_confidence=0.95
    )
    assert len(kept) == 1


def test_an_unsure_side_label_does_not_switch_plate_masking_off():
    """A front-quarter Santa Fe was labelled "side" at 0.53 and its plate was published
    readable. A shaky angle must fall back to the normal checks.
    """
    kept = backend._filter_plates(
        [plate(10, 10, 150, 60)], 100_000.0, opaque(), angle="side", angle_confidence=0.53
    )
    assert len(kept) == 1


def test_even_a_confident_side_label_does_not_switch_plate_masking_off():
    """A rear-quarter Ford Escape went out with its plate readable. The angle classifier
    is no longer trusted to turn plate masking off at all.
    """
    kept = backend._filter_plates(
        [plate(10, 10, 150, 60)], 100_000.0, opaque(), angle="side", angle_confidence=0.95
    )
    assert len(kept) == 1


def test_an_unsure_side_label_does_not_switch_plate_masking_off():
    """A front-quarter Santa Fe was labelled "side" at 0.53 and its plate was published
    readable. A shaky angle must fall back to the normal checks.
    """
    kept = backend._filter_plates(
        [plate(10, 10, 150, 60)], 100_000.0, opaque(), angle="side", angle_confidence=0.53
    )
    assert len(kept) == 1


def test_tail_lights_are_not_mistaken_for_plate_stickers():
    """A Kia Carnival came back with both red tail lights blurred."""
    img = np.full((400, 800, 3), 235, np.uint8)
    img[220:250, 60:200] = (200, 20, 20)    # left tail light
    img[220:250, 600:740] = (200, 20, 20)   # right tail light
    img[290:330, 330:470] = (240, 200, 0)   # dealer sticker in the plate mount
    found = backend._detect_plate_zone_stickers(Image.fromarray(img), (0, 0, 800, 400))
    assert [d["box"] for d in found] == [{"xmin": 330, "ymin": 290, "xmax": 470, "ymax": 330}]


def test_a_red_cars_bumper_is_not_a_sticker():
    img = np.full((400, 800, 3), 235, np.uint8)
    img[200:380, 40:760] = (210, 25, 25)    # the whole lower body, red
    found = backend._detect_plate_zone_stickers(Image.fromarray(img), (0, 0, 800, 400))
    assert found == []


def test_the_closer_pass_maps_boxes_back_into_the_crop(monkeypatch):
    seen = {}

    def fake_detector(image):
        seen["size"] = image.size
        return [{"score": 0.4, "box": {"xmin": 100, "ymin": 50, "xmax": 300, "ymax": 110}}]

    class FakeRegistry:
        plate_detector = staticmethod(fake_detector)

    monkeypatch.setattr(backend, "registry", FakeRegistry())
    crop = Image.new("RGB", (1000, 600))
    found = backend._detect_plates_closer(crop, (100, 100, 900, 500))
    assert seen["size"] == (1600, 520)
    assert found == [{"score": 0.4, "box": {"xmin": 150, "ymin": 265, "xmax": 250, "ymax": 295}}]

