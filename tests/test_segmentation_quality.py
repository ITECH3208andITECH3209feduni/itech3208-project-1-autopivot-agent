# Tests for the "did background removal actually keep the whole car" gate.
#
# These import autopivot_backend, which loads torch and ultralytics at module
# level, so they need the ML environment (requirements-ml.txt) — a GPU is not
# required and no model is downloaded, because nothing here touches the
# segmentation or detection models themselves; every cutout below is a
# synthetic RGBA image built by hand.
#
#     pytest tests/test_segmentation_quality.py -v

from PIL import Image

import autopivot_backend as backend


def opaque(width=400, height=300):
    """A cutout where every pixel belongs to the vehicle."""
    return Image.new("RGBA", (width, height), (128, 128, 128, 255))


def transparent(width=400, height=300):
    """A cutout where background removal kept nothing at all."""
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def opaque_region(box, width=400, height=300):
    """Transparent everywhere except `box`, which is fully opaque — stands
    in for a segmentation result that only kept one part of the car."""
    image = transparent(width, height)
    x1, y1, x2, y2 = box
    image.paste((128, 128, 128, 255), (x1, y1, x2, y2))
    return image


# ── _segmentation_coverage: the raw fraction ─────────────────────────────────

def test_coverage_is_measured_as_a_fraction():
    # Segmentation kept only the left half of a 0..200 wide vehicle box.
    cutout = opaque_region((0, 0, 100, 200))
    assert backend._segmentation_coverage(cutout, (0, 0, 100, 200)) == 1.0
    assert backend._segmentation_coverage(cutout, (0, 0, 200, 200)) == 0.5
    assert backend._segmentation_coverage(cutout, (100, 0, 200, 200)) == 0.0


def test_coverage_of_a_zero_sized_box_is_zero_not_a_crash():
    cutout = opaque()
    assert backend._segmentation_coverage(cutout, (50, 50, 50, 50)) == 0.0


# ── _segmentation_dropped_the_vehicle: the review-flagging gate ────────────────

def test_a_fully_segmented_vehicle_is_not_flagged():
    cutout = opaque()
    # The whole cutout is the "vehicle box" here, and it survived intact.
    assert not backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


def test_a_vehicle_mostly_dropped_by_segmentation_is_flagged():
    # Segmentation kept only the leftmost 20% of a 400px-wide vehicle box —
    # the "half car" defect this was built to catch, exaggerated.
    cutout = opaque_region((0, 0, 80, 300), width=400, height=300)
    assert backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


def test_a_vehicle_kept_comfortably_above_threshold_is_not_flagged():
    # 60% opaque clears the 35% floor with real margin.
    cutout = opaque_region((0, 0, 240, 300), width=400, height=300)
    assert not backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


def test_coverage_right_at_the_threshold_is_not_flagged():
    # Exactly 35% opaque — the boundary itself must not read as "dropped",
    # only strictly falling short of it should.
    cutout = opaque_region((0, 0, 140, 300), width=400, height=300)
    assert backend._segmentation_coverage(cutout, (0, 0, 400, 300)) == 0.35
    assert not backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


def test_coverage_just_under_the_threshold_is_flagged():
    cutout = opaque_region((0, 0, 139, 300), width=400, height=300)
    assert backend._segmentation_coverage(cutout, (0, 0, 400, 300)) < 0.35
    assert backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


def test_nothing_surviving_segmentation_at_all_is_flagged():
    cutout = transparent()
    assert backend._segmentation_dropped_the_vehicle(cutout, (0, 0, 400, 300))


# ── _box_in_crop: the coordinate mapping the gate is wired through ────────────
#
# Getting this arithmetic wrong would not crash anything — it would just
# compare segmentation coverage against the wrong pixels, either never
# firing or always firing. Worth pinning on its own rather than only
# trusting it inline in PipelineProcessor.process().

def box(xmin, ymin, xmax, ymax):
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


def test_box_in_crop_translates_by_the_crops_own_top_left():
    detection = box(120, 80, 420, 380)
    crop_coords = (100, 60, 440, 400)  # some padding applied on every side
    assert backend._box_in_crop(detection, crop_coords) == (20, 20, 320, 320)


def test_box_in_crop_is_the_identity_when_the_crop_has_no_offset():
    detection = box(0, 0, 200, 150)
    assert backend._box_in_crop(detection, (0, 0, 200, 150)) == (0, 0, 200, 150)


def test_box_in_crop_matches_a_real_crop_with_padding():
    """
    End-to-end against the real `_crop_with_padding`, not a hand-picked
    offset: whatever padding that function actually applies, mapping the
    original detection box through _box_in_crop must land it back at
    (0, 0, box_width, box_height) inside the crop — the padding is symmetric
    around the box by construction, so the box's own top-left in the crop is
    exactly the padding amount, and its bottom-right is padding + the box's
    own size.
    """
    source = Image.new("RGB", (1000, 800), (50, 50, 50))
    detection = box(200, 150, 700, 650)  # 500x500

    crop, coords = backend._crop_with_padding(source, detection, padding_ratio=0.08)
    mapped = backend._box_in_crop(detection, coords)

    pad = int(500 * 0.08)  # _crop_with_padding's own padding for a 500px box
    assert mapped == (pad, pad, pad + 500, pad + 500)
    assert crop.size == (500 + pad * 2, 500 + pad * 2)
