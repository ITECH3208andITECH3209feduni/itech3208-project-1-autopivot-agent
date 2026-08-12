# Tests for placing a cut-out vehicle onto a backdrop.
#
# compositing.py imports only cv2, numpy and PIL — no torch, no model — so
# these run anywhere those three are installed:
#
#     pytest tests/test_compositing.py -v

import numpy as np
import pytest
from PIL import Image

import compositing


def block(width=200, height=100, colour=(180, 40, 40)):
    """A solid opaque rectangle standing in for a vehicle cutout."""
    return Image.new("RGBA", (width, height), (*colour, 255))


def cutout_on_padding(pad=40, width=200, height=100):
    """A vehicle with transparent margin around it, as segmentation produces."""
    canvas = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    canvas.paste(block(width, height), (pad, pad))
    return canvas


def backdrop(width=1600, height=1200, colour=(200, 200, 205)):
    return Image.new("RGBA", (width, height), (*colour, 255))


# ── Mask cleanup ───────────────────────────────────────────────────────────────

def test_refine_alpha_mask_snaps_near_extremes():
    raw = np.full((40, 40), 1, dtype=np.uint8)
    raw[10:30, 10:30] = 254
    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined.min() == 0, "near-zero alpha must become fully transparent"
    assert refined.max() == 255, "near-solid alpha must become fully opaque"


def test_refine_alpha_mask_closes_a_pinhole():
    raw = np.full((60, 60), 255, dtype=np.uint8)
    raw[30, 30] = 0  # single-pixel hole
    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined[30, 30] == 255


def test_trim_transparent_removes_the_margin():
    trimmed = compositing.trim_transparent(cutout_on_padding(pad=40))
    # 2px margin is kept deliberately, so expect the block plus a little.
    assert 200 <= trimmed.width <= 206
    assert 100 <= trimmed.height <= 106


def test_trim_transparent_survives_a_fully_empty_cutout():
    empty = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert compositing.trim_transparent(empty).size == (50, 50)


# ── Geometry ───────────────────────────────────────────────────────────────────

def test_contact_y_ignores_a_stray_low_pixel():
    """
    One column of leftover mask below the car must not lift it off the floor.
    The quantile is the whole point of not using the lowest opaque pixel.
    """
    alpha = np.zeros((200, 200), dtype=np.uint8)
    alpha[50:150, :] = 255      # the body, bottom at y=149
    alpha[150:199, 5] = 255     # one stray column reaching much lower

    vehicle = Image.new("RGBA", (200, 200))
    vehicle.putalpha(Image.fromarray(alpha, "L"))

    assert compositing._contact_y(vehicle) < 160


def test_visible_bounds_ignores_transparent_margin():
    assert compositing._visible_bounds(cutout_on_padding(pad=40)) == (40, 40, 240, 140)


def test_dealer_backdrop_keeps_its_own_resolution():
    result, meta = compositing.compose(cutout_on_padding(), backdrop(1600, 1200))
    assert result.size == (1600, 1200)
    assert meta["output_size"] == {"width": 1600, "height": 1200}


def test_oversized_backdrop_is_capped():
    result, _ = compositing.compose(cutout_on_padding(), backdrop(4000, 3000))
    assert result.width == compositing.MAX_CANVAS_WIDTH
    assert result.height == 1800  # aspect preserved


def test_studio_preset_uses_its_measured_canvas():
    preset = compositing.STUDIO_FULL
    result, meta = compositing.compose(cutout_on_padding(), backdrop(2000, 1500), preset)
    assert result.size == (1280, 960)
    assert meta["backdrop_style"] == "studio_full"
    assert meta["shadow_applied"] is True


def test_centre_placement_applies_no_shadow():
    _, meta = compositing.compose(
        cutout_on_padding(), backdrop(), compositing.STUDIO_CLOSEUP
    )
    assert meta["shadow_applied"] is False
    assert meta["ground_aligned"] is False


# ── The vehicle lands where it should ──────────────────────────────────────────

def opaque_bounds(image):
    alpha = np.array(image.convert("RGBA").getchannel("A"))
    ys, xs = np.where(alpha > 250)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_vehicle_is_horizontally_centred_on_a_dealer_backdrop():
    canvas_w = 1600
    result, _ = compositing.compose(cutout_on_padding(), backdrop(canvas_w, 1200))

    # The backdrop is opaque everywhere, so locate the car by its colour.
    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    xs = np.where(red.any(axis=0))[0]

    centre = (xs.min() + xs.max()) / 2
    assert abs(centre - canvas_w / 2) < canvas_w * 0.02


def test_vehicle_sits_on_the_ground_line():
    canvas_h = 1200
    result, _ = compositing.compose(cutout_on_padding(), backdrop(1600, canvas_h))

    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    ys = np.where(red.any(axis=1))[0]

    # Default ground_y_ratio is 0.84.
    assert abs(ys.max() - canvas_h * 0.84) < canvas_h * 0.03


def test_shadow_darkens_the_floor_beneath_the_vehicle():
    plain = backdrop(1600, 1200, colour=(200, 200, 205))
    result, _ = compositing.compose(cutout_on_padding(), plain)

    pixels = np.array(result.convert("RGB")).astype(np.int16)
    # A band just below the ground line, away from the car's own colour.
    band = pixels[1030:1060, 300:1300]
    assert band.mean() < 200, "expected a shadow, floor is unchanged"


# ── Composite must not fall over on awkward sizes ──────────────────────────────

@pytest.mark.parametrize("size", [(320, 240), (400, 300), (2000, 400), (300, 900)])
def test_small_and_extreme_backdrops_do_not_raise(size):
    """
    Shadows are wider than the vehicle and padded by twice the blur radius, so
    on a small backdrop the paste destination goes negative or overruns the
    edge. This is the case that crashed before _alpha_composite_at.
    """
    result, _ = compositing.compose(cutout_on_padding(), backdrop(*size))
    assert result.size[0] > 0 and result.size[1] > 0


def test_composite_at_crops_rather_than_raising():
    canvas = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
    layer = Image.new("RGBA", (200, 200), (255, 0, 0, 255))

    for position in [(-150, -150), (-50, -50), (50, 50), (150, 150), (500, 500)]:
        compositing._alpha_composite_at(canvas, layer, position)

    assert canvas.size == (100, 100)


# ── Colour matching stays gentle ───────────────────────────────────────────────

def test_colour_match_moves_towards_the_backdrop_but_not_far():
    vehicle = block(200, 100, colour=(180, 40, 40))
    scene = backdrop(400, 300, colour=(40, 40, 60))  # much darker

    matched = compositing.match_colour(vehicle, scene, 50, 50)

    before = np.array(vehicle.convert("RGB")).astype(np.int16)
    after = np.array(matched.convert("RGB")).astype(np.int16)
    shift = np.abs(after - before).mean()

    assert shift > 0, "colour matching did nothing"
    assert shift < 40, "colour matching repainted the car"


def test_colour_match_on_an_empty_cutout_is_a_no_op():
    empty = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert compositing.match_colour(empty, backdrop(200, 200), 0, 0) is empty
