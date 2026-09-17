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


# ── Angle: a plate cannot be seen face-on in profile ────────────────────────────
#
# The photo-507 defect: YOLOS detected a plate-shaped, plate-sized box
# sitting squarely on the vehicle (the front wheel, as it turned out) in a
# dead-on side photograph, and it cleared every check above — shape, size,
# and coverage all look exactly like a real plate would. Only the angle the
# photograph was taken from can catch this one: a plate mounted flush to a
# bumper is edge-on to a side-view camera and is not legible, so any
# detection reported for a "side"-classified photo is something else on the
# car, not a plate.

def test_plate_is_rejected_on_a_side_angle_photograph():
    # Otherwise a perfect match: right shape, right size, fully on-vehicle.
    good_plate = plate(130, 200, 270, 250)
    assert backend._filter_plates(
        [good_plate], 100_000.0, opaque(), angle="side",
    ) == []


def test_side_angle_rejection_does_not_short_circuit_the_area_check_note():
    # Multiple detections on a side shot are all dropped together, not just
    # thinned down to whichever survives geometry.
    plates = [plate(130, 200, 270, 250), plate(10, 10, 150, 60)]
    assert backend._filter_plates(plates, 100_000.0, opaque(), angle="side") == []


@pytest.mark.parametrize("angle", ["front", "front_quarter", "rear_quarter", "rear", None])
def test_plate_survives_on_every_angle_that_can_actually_show_one(angle):
    good_plate = plate(130, 200, 270, 250)
    kept = backend._filter_plates([good_plate], 100_000.0, opaque(), angle=angle)
    assert len(kept) == 1


# ── Plate-zone sticker fallback: something that doesn't look like a plate ──────
#
# The job-568 defect: a red "Encar" marketplace sticker sat in the front
# plate mount, nothing like a real plate (solid saturated colour vs. a real
# plate's white/black), so YOLOS never proposed a box there at all —
# lowering PLATE_CONFIDENCE can't help when the model never nominates the
# region in the first place. _detect_plate_zone_stickers is a second,
# colour-only search that hands any hit through the same _filter_plates
# checks a real detection would face.

def crop_with_zone_sticker(
    *, colour=(200, 40, 40), rect=(150, 200, 230, 230),
    width=400, height=300, base_colour=(40, 40, 45),
):
    """
    A photographic crop (not a cutout — plain RGB) with a solid coloured
    rectangle painted at `rect` (x1, y1, x2, y2), standing in for a bumper
    with something stuck to it. Paired with `vehicle_box_for_zone_sticker`
    below, whose default puts (150, 200, 230, 230) — an 80×30 block, aspect
    2.67 — inside the searched zone.
    """
    array = np.full((height, width, 3), base_colour, dtype=np.uint8)
    x1, y1, x2, y2 = rect
    array[y1:y2, x1:x2] = colour
    return Image.fromarray(array, "RGB")


def vehicle_box_for_zone_sticker():
    """The vehicle box that makes crop_with_zone_sticker's default rect land
    inside the searched zone: vehicle 360×260 at (20, 20) puts the zone at
    roughly x 121–279, y 163–267 — see PLATE_ZONE_X_RATIO/Y_RATIO."""
    return (20, 20, 380, 280)


def test_a_saturated_sticker_in_the_plate_zone_is_detected():
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())

    assert len(detections) == 1
    box = detections[0]["box"]
    assert (box["xmin"], box["ymin"], box["xmax"], box["ymax"]) == (150, 200, 230, 230)


def test_a_sticker_off_centre_in_a_quarter_angle_shot_is_still_detected():
    """
    Regression pin for the real job-568 photo: a front-quarter shot puts the
    near corner — and the sticker mounted on it — well off the horizontal
    middle of the vehicle's own bounding box, at roughly 15% of its width in
    from the left edge, not the ~50% a straight-on shot would put it at. An
    earlier, centred x-band (28-72%) missed this outright.
    """
    vehicle_box = (20, 20, 380, 280)  # 360 wide — 15% in from the left is x ~= 74
    crop = crop_with_zone_sticker(rect=(50, 210, 110, 235))
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box)
    assert len(detections) == 1


def test_a_low_saturation_patch_is_not_detected():
    """A grey/black scuff or panel gap must not be flagged just for sitting
    in the right place — only real colour does that."""
    crop = crop_with_zone_sticker(colour=(190, 185, 180))
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_saturated_patch_at_the_very_edge_of_the_box_is_not_detected():
    """PLATE_ZONE_X_RATIO's band is wide (it has to cover quarter-angle
    shots, see its comment) but still excludes the outermost sliver on each
    side, to stay clear of a wing mirror or a wheel right at the box edge."""
    crop = crop_with_zone_sticker(rect=(20, 200, 35, 230))  # flush with the vehicle box's own edge
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_saturated_patch_high_on_the_body_is_not_detected():
    """A red decal or badge on the bonnet/roof is nowhere near where a plate
    mounts — outside PLATE_ZONE_Y_RATIO's lower band."""
    crop = crop_with_zone_sticker(rect=(150, 40, 230, 70))  # near the top of the vehicle box
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_scattered_specular_highlights_are_not_detected():
    """A handful of small bright/saturated pixels — reflections off trim or
    paint flake — must not add up to a detection the way one solid block
    does; each patch here is a third of PLATE_ZONE_MIN_AREA_PX."""
    array = np.full((300, 400, 3), (40, 40, 45), dtype=np.uint8)
    for x in (160, 180, 200, 220):
        array[210:216, x:x + 6] = (200, 40, 40)  # 6x6 = 36px, well under the area floor
    crop = Image.fromarray(array, "RGB")
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_thin_saturated_stripe_is_not_detected():
    """Low extent (area / bounding-box area) rejects a scattered or
    irregular shape even when its bounding box would otherwise qualify —
    a diagonal reflection streak, not a solid sticker."""
    array = np.full((300, 400, 3), (40, 40, 45), dtype=np.uint8)
    for i in range(60):
        array[200 + i // 3, 150 + i] = (200, 40, 40)  # a thin diagonal line, not a block
    crop = Image.fromarray(array, "RGB")
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_narrow_saturated_block_like_a_tail_light_lens_is_not_detected():
    """
    The job-611/615 defect: widening PLATE_ZONE_X_RATIO to reach a
    quarter-angle sticker also let a tail lamp's own lens/reflector segment
    into the search band on a straight rear shot — a solid, saturated,
    plate-aspect block, just far too narrow to be a plate or a mounted
    sticker. 30px wide in a 360px-wide vehicle box is a ~8% width ratio,
    under PLATE_ZONE_MIN_WIDTH_RATIO's 12% floor; the default sticker rect
    elsewhere in this file is ~22%, well clear of it.
    """
    crop = crop_with_zone_sticker(rect=(150, 210, 180, 225))  # 30x15, aspect 2.0, solid
    assert backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker()) == []


def test_a_wide_sticker_just_above_the_width_floor_is_still_detected():
    """Pin the floor from the other side: a block only a little wider than
    the rejected one above must still come through."""
    crop = crop_with_zone_sticker(rect=(150, 210, 195, 225))  # 45px wide, ratio 0.125
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    assert len(detections) == 1


def test_an_empty_or_invalid_vehicle_box_yields_no_detections():
    crop = crop_with_zone_sticker()
    assert backend._detect_plate_zone_stickers(crop, (100, 100, 100, 100)) == []
    assert backend._detect_plate_zone_stickers(crop, (200, 200, 50, 50)) == []


def test_zone_detection_survives_filter_plates_like_a_real_plate():
    """The whole point: once found, it is judged exactly as a real detection
    would be — aspect, area, coverage, angle — not waved through."""
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    kept = backend._filter_plates(detections, 100_000.0, opaque(400, 300), angle="front")
    assert len(kept) == 1


def test_zone_detection_is_rejected_on_a_side_angle_like_any_other_plate():
    crop = crop_with_zone_sticker()
    detections = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    assert backend._filter_plates(detections, 100_000.0, opaque(400, 300), angle="side") == []


def test_zone_detection_merges_with_model_detections_without_duplicating():
    """The real call site concatenates _detect_plates(crop) with this
    function's output before filtering — a photo with both a real plate the
    model found and this sticker should end up with both, not one clobbering
    the other."""
    crop = crop_with_zone_sticker()
    sticker = backend._detect_plate_zone_stickers(crop, vehicle_box_for_zone_sticker())
    model_found = [plate(10, 10, 150, 60)]  # unrelated region, elsewhere on the vehicle
    combined = backend._filter_plates(
        model_found + sticker, 100_000.0, opaque(400, 300), angle="front",
    )
    assert len(combined) == 2


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


# ── Brand overlay loader ─────────────────────────────────────────────────────
#
# `_brand_plate_overlay()` is what `process()` calls on every job to decide
# whether a detected plate gets the AutoPivot wordmark or the ordinary
# PLATE_TREATMENT obscuring. It caches across calls (module-level globals),
# so each test resets both before it runs rather than relying on order.

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
    logo_path.unlink()  # if this call reopens the file, it will fail
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
    """
    Not a mock — this is the actual file `PLATE_BRAND_LOGO_PATH` defaults to,
    so a broken or accidentally-overwritten asset fails the suite instead of
    silently falling back to blur in production.
    """
    logo = Image.open(backend.PLATE_BRAND_LOGO_PATH).convert("RGBA")
    aspect = logo.width / logo.height
    assert backend.PLATE_MIN_ASPECT <= aspect <= backend.PLATE_MAX_ASPECT
    # Fully opaque somewhere in the middle — i.e. it is not an empty/blank file.
    assert np.array(logo.getchannel("A"))[logo.height // 2, logo.width // 2] > 0


# ── Confidence threshold ───────────────────────────────────────────────────────

def test_box_area_is_clamped_at_zero():
    assert backend._box_area({"xmin": 10, "ymin": 10, "xmax": 5, "ymax": 5}) == 0.0
    assert backend._box_area({"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 4}) == 40.0
