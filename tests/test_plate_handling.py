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
    (10, 10, 60, 60),
    (10, 10, 40, 200),
    (10, 10, 400, 20),
])
def test_boxes_that_are_not_plate_shaped_are_rejected(box):
    assert backend._filter_plates([plate(*box)], 100_000.0, opaque()) == []


# ── Size relative to the vehicle ───────────────────────────────────────────────

def test_box_covering_most_of_the_vehicle_is_rejected():
    assert backend._filter_plates([plate(0, 0, 280, 100)], 70_000.0, opaque()) == []


def test_area_check_is_skipped_when_no_vehicle_area_is_known():
    kept = backend._filter_plates([plate(0, 0, 280, 100)], 0.0, None)
    assert len(kept) == 1


# ── Angle: a plate cannot be seen face-on in profile ────────────────────────────

def test_plate_is_rejected_on_a_side_angle_photograph():
    good_plate = plate(130, 200, 270, 250)
    assert backend._filter_plates(
        [good_plate], 100_000.0, opaque(), angle="side",
    ) == []


def test_side_angle_rejection_does_not_short_circuit_the_area_check_note():
    plates = [plate(130, 200, 270, 250), plate(10, 10, 150, 60)]
    assert backend._filter_plates(plates, 100_000.0, opaque(), angle="side") == []


@pytest.mark.parametrize("angle", ["front", "front_quarter", "rear_quarter", "rear", None])
def test_plate_survives_on_every_angle_that_can_actually_show_one(angle):
    good_plate = plate(130, 200, 270, 250)
    kept = backend._filter_plates([good_plate], 100_000.0, opaque(), angle=angle)
    assert len(kept) == 1


# ── Plate-zone sticker fallback: something that doesn't look like a plate ──────

def crop_with_zone_sticker(
    *, colour=(200, 40, 40), rect=(150, 200, 230, 230),
    width=400, height=300, base_colour=(40, 40, 45),
):
    """A photographic crop with a solid coloured rectangle painted at `rect`."""
    array = np.full((height, width, 3), base_colour, dtype=np.uint8)
    x1, y1, x2, y2 = rect
    array[y1:y2, x1:x2] = colour
    return Image.fromarray(array, "RGB")


def vehicle_box_for_zone_sticker():
    """The vehicle box that puts crop_with_zone_sticker's default rect inside
    the searched zone."""
    return (20, 20, 380, 280)


def test_a_saturated_sticker_in_the_plate_zone_is_detected():
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())

    assert len(detections) == 1
    box = detections[0]["box"]
    assert (box["xmin"], box["ymin"], box["xmax"], box["ymax"]) == (150, 200, 230, 230)


def test_a_sticker_off_centre_in_a_quarter_angle_shot_is_still_detected():
    vehicle_box = (20, 20, 380, 280)
    crop = crop_with_zone_sticker(rect=(50, 210, 110, 235))
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box)
    assert len(detections) == 1


def test_a_low_saturation_patch_is_not_detected():
    crop = crop_with_zone_sticker(colour=(190, 185, 180))
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_saturated_patch_at_the_very_edge_of_the_box_is_not_detected():
    crop = crop_with_zone_sticker(rect=(20, 200, 35, 230))
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_saturated_patch_high_on_the_body_is_not_detected():
    crop = crop_with_zone_sticker(rect=(150, 40, 230, 70))
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_scattered_specular_highlights_are_not_detected():
    array = np.full((300, 400, 3), (40, 40, 45), dtype=np.uint8)
    for x in (160, 180, 200, 220):
        array[210:216, x:x + 6] = (200, 40, 40)
    crop = Image.fromarray(array, "RGB")
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_thin_saturated_stripe_is_not_detected():
    array = np.full((300, 400, 3), (40, 40, 45), dtype=np.uint8)
    for i in range(60):
        array[200 + i // 3, 150 + i] = (200, 40, 40)
    crop = Image.fromarray(array, "RGB")
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_narrow_saturated_block_like_a_tail_light_lens_is_not_detected():
    crop = crop_with_zone_sticker(rect=(150, 210, 180, 225))
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_wide_sticker_just_above_the_width_floor_is_still_detected():
    crop = crop_with_zone_sticker(rect=(150, 210, 195, 225))
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    assert len(detections) == 1


def test_an_empty_or_invalid_vehicle_box_yields_no_detections():
    crop = crop_with_zone_sticker()
    assert backend._detect_plate_zone_stickers(crop, (100, 100, 100, 100)) == []
    assert backend._detect_plate_zone_stickers(crop, (200, 200, 50, 50)) == []


def test_zone_detection_survives_filter_plates_like_a_real_plate():
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    kept = backend._filter_plates(detections, 100_000.0, opaque(400, 300), angle="front")
    assert len(kept) == 1


def test_zone_detection_is_rejected_on_a_side_angle_like_any_other_plate():
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    assert backend._filter_plates(detections, 100_000.0, opaque(400, 300), angle="side") == []


def test_zone_detection_merges_with_model_detections_without_duplicating():
    crop = crop_with_zone_sticker()
    sticker = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    model_found = [plate(10, 10, 150, 60)]
    combined = backend._filter_plates(
        model_found + sticker, 100_000.0, opaque(400, 300), angle="front",
    )
    assert len(combined) == 2


# ── Coverage: the regression this was built for ────────────────────────────────

def test_plate_detected_off_the_vehicle_is_rejected():
    floating = (200, 200, 340, 250)
    cutout = cutout_with_hole(floating)
    assert backend._filter_plates([plate(*floating)], 100_000.0, cutout) == []


def test_plate_on_the_vehicle_survives():
    cutout = cutout_with_hole((0, 0, 20, 20))
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
    image = Image.new("RGBA", (200, 200), (10, 20, 30, 0))
    treated = backend._apply_plate_treatment(image, [plate(50, 50, 190, 100)], None)

    alpha = np.array(treated.getchannel("A"))
    assert alpha.max() == 0, "treatment must not make transparent pixels opaque"


def test_overlay_path_still_composites():
    image = Image.new("RGBA", (200, 200), (10, 20, 30, 255))
    overlay = Image.new("RGBA", (60, 20), (255, 0, 0, 255))

    treated = backend._apply_plate_treatment(image, [plate(50, 50, 190, 100)], overlay)
    centre = treated.getpixel((120, 75))

    assert centre[:3] == (255, 0, 0)


# ── Brand overlay loader ─────────────────────────────────────────────────────

def _reset_brand_overlay_cache(monkeypatch):
    monkeypatch.setattr(backend, "_brand_plate_overlay_cache", None)
    monkeypatch.setattr(backend, "_brand_plate_overlay_loaded", False)


def test_brand_overlay_is_none_when_disabled(monkeypatch):
    _reset_brand_overlay_cache(monkeypatch)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_ENABLED", False)
    assert backend._brand_plate_overlay() is None


def test_brand_overlay_loads_the_configured_asset(monkeypatch, tmp_path):
    _reset_brand_overlay_cache(monkeypatch)
    logo_path = tmp_path / "logo.png"
    Image.new("RGBA", (280, 100), (250, 250, 248, 255)).save(logo_path)

    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_ENABLED", True)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_PATH", str(logo_path))

    overlay = backend._brand_plate_overlay()
    assert overlay is not None
    assert overlay.mode == "RGBA"
    assert overlay.size == (280, 100)


def test_brand_overlay_is_cached_after_the_first_load(monkeypatch, tmp_path):
    _reset_brand_overlay_cache(monkeypatch)
    logo_path = tmp_path / "logo.png"
    Image.new("RGBA", (280, 100), (250, 250, 248, 255)).save(logo_path)

    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_ENABLED", True)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_PATH", str(logo_path))

    first = backend._brand_plate_overlay()
    logo_path.unlink()
    second = backend._brand_plate_overlay()

    assert first is second


def test_brand_overlay_falls_back_to_none_when_the_asset_is_missing(monkeypatch, tmp_path, caplog):
    _reset_brand_overlay_cache(monkeypatch)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_ENABLED", True)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_PATH", str(tmp_path / "missing.png"))

    with caplog.at_level("WARNING", logger="autopivot"):
        overlay = backend._brand_plate_overlay()

    assert overlay is None
    assert "could not be loaded" in caplog.text


def test_brand_overlay_falls_back_to_none_for_a_corrupt_asset(monkeypatch, tmp_path):
    _reset_brand_overlay_cache(monkeypatch)
    bad_path = tmp_path / "logo.png"
    bad_path.write_bytes(b"not actually a png")

    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_ENABLED", True)
    monkeypatch.setattr(backend, "PLATE_BRAND_LOGO_PATH", str(bad_path))

    assert backend._brand_plate_overlay() is None


def test_the_shipped_brand_logo_asset_loads_and_is_plate_shaped():
    logo = Image.open(backend.PLATE_BRAND_LOGO_PATH).convert("RGBA")
    aspect = logo.width / logo.height
    assert backend.PLATE_MIN_ASPECT <= aspect <= backend.PLATE_MAX_ASPECT
    assert np.array(logo.getchannel("A"))[logo.height // 2, logo.width // 2] > 0


# ── Confidence threshold ───────────────────────────────────────────────────────

def test_box_area_is_clamped_at_zero():
    assert backend._box_area({"xmin": 10, "ymin": 10, "xmax": 5, "ymax": 5}) == 0.0
    assert backend._box_area({"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 4}) == 40.0
