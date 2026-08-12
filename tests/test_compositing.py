# Tests for placing a cut-out vehicle onto a backdrop.
#
# compositing.py imports only cv2, numpy and PIL — no torch, no model — so
# these run anywhere those three are installed:
#
#     pytest tests/test_compositing.py -v

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image, ImageDraw

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


# ── Size consistency across angles ─────────────────────────────────────────────
#
# The defect these cover: every shot was scaled to fill the available box, so a
# head-on shot (about as wide as it is tall) ran out of height first and was
# enlarged until it filled the frame, while a side-on shot of the same car ran
# out of width first and came out roughly half the size. A dealer flicking
# through the gallery saw the car grow and shrink.

# One car, 4.7 m long and 1.5 m tall, seen from several directions. The numbers
# are projected-length-over-height, which is what the camera actually sees.
CAR_ASPECTS = {
    "side": 3.13,           # 4.7 / 1.5
    "front_quarter": 2.40,
    "rear_quarter": 2.40,
    "front": 1.20,          # 1.8 wide / 1.5 tall
    "rear": 1.20,
}


def car_at_aspect(aspect: float, height: int = 300) -> Image.Image:
    """The same notional car seen at an angle giving this width/height ratio."""
    width = max(1, round(height * aspect))
    pad = 30
    canvas = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    canvas.paste(block(width, height), (pad, pad))
    return canvas


def rendered_vehicle_height(result: Image.Image) -> int:
    """Height of the car in the finished frame, found by its colour."""
    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    rows = np.where(red.any(axis=1))[0]
    return 0 if rows.size == 0 else int(rows.max() - rows.min() + 1)


def test_one_car_is_one_size_whatever_way_it_faces():
    """
    This is the regression the height normalisation exists for. Against the
    fill-the-box rule the head-on shot rendered roughly twice the height of the
    side-on one; they should now agree closely.
    """
    heights = {
        angle: rendered_vehicle_height(
            compositing.compose(car_at_aspect(aspect), backdrop(1600, 1200), angle=angle)[0]
        )
        for angle, aspect in CAR_ASPECTS.items()
    }

    assert min(heights.values()) > 0, f"nothing rendered: {heights}"
    spread = max(heights.values()) / min(heights.values())
    assert spread < 1.10, f"car changes size across angles: {heights}"


def test_size_consistency_holds_on_the_measured_studio_platform():
    heights = {
        angle: rendered_vehicle_height(
            compositing.compose(
                car_at_aspect(aspect), backdrop(2000, 1500),
                compositing.STUDIO_FULL, angle=angle,
            )[0]
        )
        for angle, aspect in CAR_ASPECTS.items()
    }
    spread = max(heights.values()) / min(heights.values())
    assert spread < 1.10, f"car changes size across angles on the platform: {heights}"


def test_fill_the_box_scaling_would_fail_this():
    """
    Guards the guard. If height normalisation silently stops engaging, the test
    above must not keep passing for some other reason — so assert directly that
    the old rule produces the spread we are claiming to have fixed.
    """
    canvas_w, canvas_h = 1600, 1200
    max_w = canvas_w * compositing.DEALER_BACKDROP.vehicle_width_ratio
    max_h = canvas_h * compositing.DEALER_BACKDROP.vehicle_height_ratio

    def fill_the_box_height(aspect: float, height: int = 300) -> float:
        width = height * aspect
        return height * min(max_w / width, max_h / height)

    old = {a: fill_the_box_height(r) for a, r in CAR_ASPECTS.items()}
    assert max(old.values()) / min(old.values()) > 1.9, (
        f"the old rule no longer misbehaves, so the fix is untested: {old}"
    )


def test_height_normalisation_is_reported():
    _, meta = compositing.compose(car_at_aspect(3.13), backdrop(1600, 1200))
    assert meta["height_normalised"] is True


def test_an_implausibly_long_cutout_falls_back_rather_than_overflowing():
    """A panorama is not a car; it must not be scaled to a car's height and
    then run off the sides of the frame."""
    result, meta = compositing.compose(car_at_aspect(9.0), backdrop(1600, 1200))
    assert meta["height_normalised"] is False
    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    columns = np.where(red.any(axis=0))[0]
    assert columns.min() >= 0 and columns.max() < 1600


# ── Angle ──────────────────────────────────────────────────────────────────────

def test_angle_is_optional_and_changes_nothing_when_absent():
    """Callers that predate the angle argument must compose byte-identically."""
    car = car_at_aspect(3.13)
    without, meta_a = compositing.compose(car, backdrop(1400, 1000))
    unknown, meta_b = compositing.compose(car, backdrop(1400, 1000), angle="nonsense-label")

    assert np.array_equal(np.array(without), np.array(unknown)), (
        "an unrecognised angle must fall back to the no-angle geometry"
    )
    assert meta_a["shot_angle"] is None
    assert meta_b["shot_angle"] == "nonsense-label"


@pytest.mark.parametrize("angle", ["front", "front_quarter", "side", "rear_quarter", "rear"])
def test_every_known_angle_composes(angle):
    result, meta = compositing.compose(
        car_at_aspect(CAR_ASPECTS[angle]), backdrop(1600, 1200), angle=angle
    )
    assert result.size == (1600, 1200)
    assert meta["shot_angle"] == angle


# ── Reflection ─────────────────────────────────────────────────────────────────

def test_reflection_only_on_a_surface_we_measured():
    """
    A dealer's backdrop may be carpet, gravel or a workshop floor. Reflecting a
    car in gravel looks worse than not reflecting it, so the reflection is
    limited to the platform whose finish we can actually see.
    """
    _, studio = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_FULL
    )
    _, dealer = compositing.compose(car_at_aspect(3.13), backdrop(1600, 1200))
    _, closeup = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_CLOSEUP
    )

    assert studio["reflection_applied"] is True
    assert dealer["reflection_applied"] is False, "we do not know a dealer's floor is polished"
    assert closeup["reflection_applied"] is False, "a wall-backed close-up has no floor"


def test_reflection_darkens_the_platform_below_the_car():
    car = car_at_aspect(3.13)
    scene = backdrop(2000, 1500)

    lit, _ = compositing.compose(car, scene, compositing.STUDIO_FULL)
    plain_preset = replace(compositing.STUDIO_FULL, reflection_strength=0.0)
    unlit, meta = compositing.compose(car, scene, plain_preset)
    assert meta["reflection_applied"] is False

    # Just under the contact line, across the middle of the platform.
    contact = round(960 * compositing.STUDIO_FULL.platform_contact_y_ratio)
    band = slice(contact + 4, contact + 40)
    with_reflection = np.array(lit.convert("RGB"))[band, 400:900].astype(np.int16)
    without = np.array(unlit.convert("RGB"))[band, 400:900].astype(np.int16)

    assert with_reflection.mean() < without.mean(), "reflection did not darken the floor"


def test_reflection_stays_on_the_platform():
    """Clipped to the ellipse: a mirror image running off the base onto the
    showroom floor is worse than none at all."""
    result, _ = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_FULL
    )
    bare, _ = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500),
        replace(compositing.STUDIO_FULL, reflection_strength=0.0),
    )
    lit = np.array(result.convert("RGB")).astype(np.int16)
    unlit = np.array(bare.convert("RGB")).astype(np.int16)
    difference = np.abs(lit - unlit).sum(axis=2)

    changed_rows = np.where((difference > 6).any(axis=1))[0]
    if changed_rows.size:
        # Nothing should change above the platform's own top edge.
        platform_top = round(960 * compositing.STUDIO_FULL.platform_box[1])
        assert changed_rows.min() >= platform_top - 2, (
            f"reflection reached row {changed_rows.min()}, above the platform at {platform_top}"
        )


def silhouette(aspect: float, height: int = 520) -> Image.Image:
    """
    A car-shaped cutout rather than a rectangle.

    This matters. The rectangle above has its visible aspect exactly equal to
    the nominal one, which happens to sit inside the width limit at every
    angle. A real silhouette is wider than its body once wheels and mirrors are
    in frame — a side-on shot measures nearer 3.6 to 1 — and that is precisely
    the case that used to fall out of height normalisation.
    """
    width = round(height * aspect)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    body_top, body_bottom = int(height * 0.48), int(height * 0.83)
    draw.rounded_rectangle(
        (width * 0.03, body_top, width * 0.97, body_bottom),
        radius=height * 0.11, fill=(180, 40, 40, 255),
    )
    draw.rounded_rectangle(
        (width * 0.25, height * 0.17, width * 0.75, body_top + height * 0.04),
        radius=height * 0.13, fill=(180, 40, 40, 255),
    )
    wheel = height * 0.18
    for centre in (width * 0.23, width * 0.78):
        draw.ellipse(
            (centre - wheel, body_bottom - wheel * 0.9,
             centre + wheel, body_bottom + wheel * 0.9),
            fill=(180, 40, 40, 255),
        )
    return image


def test_a_car_shaped_cutout_is_also_one_size_at_every_angle():
    """
    The regression the rectangle test missed. A side-on silhouette exceeded the
    width limit by a hair, and the accept-or-abandon rule dropped it all the
    way back to fill-the-box — twelve per cent smaller than the same car at
    every other angle, which is the exact defect being fixed.
    """
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    assert backdrop_image is not None, "studio-full.png is missing from assets"

    heights = {}
    for angle, aspect in CAR_ASPECTS.items():
        result, meta = compositing.compose(
            silhouette(aspect), backdrop_image, preset, angle=angle
        )
        heights[angle] = rendered_vehicle_height(result)
        assert meta["height_normalised"] is True, f"{angle} fell back to fill-the-box"

    spread = max(heights.values()) / min(heights.values())
    assert spread < 1.03, f"car changes size across angles: {heights}"


def test_every_angle_stays_on_the_measured_platform():
    """A car overhanging the base reads as floating, which is the failure the
    platform was measured to avoid."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    width = preset.output_size[0]
    left_edge = width * preset.platform_box[0]
    right_edge = width * preset.platform_box[2]

    for angle, aspect in CAR_ASPECTS.items():
        result, _ = compositing.compose(
            silhouette(aspect), backdrop_image, preset, angle=angle
        )
        pixels = np.array(result.convert("RGB"))
        car = (pixels[:, :, 0] > 110) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
        columns = np.where(car.any(axis=0))[0]
        assert columns.min() >= left_edge - 6, f"{angle} overhangs the platform on the left"
        assert columns.max() <= right_edge + 6, f"{angle} overhangs the platform on the right"
