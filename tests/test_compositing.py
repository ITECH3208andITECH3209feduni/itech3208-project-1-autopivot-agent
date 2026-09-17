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
    raw[30, 30] = 0
    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined[30, 30] == 255


def test_refine_alpha_mask_removes_a_disconnected_background_blob():
    raw = np.zeros((200, 300), dtype=np.uint8)
    raw[50:150, 20:220] = 255
    raw[10:40, 260:290] = 255

    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined[100, 120] == 255, "the vehicle itself must survive"
    assert refined[25, 275] == 0, "the disconnected object must be removed"


def test_refine_alpha_mask_removes_a_blob_joined_only_by_a_faint_shadow():
    raw = np.zeros((200, 300), dtype=np.uint8)
    raw[50:150, 20:220] = 255
    raw[120:140, 220:250] = 45
    raw[110:150, 250:280] = 220

    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined[100, 120] == 255, "the vehicle itself must survive"
    assert refined[130, 265] == 0, "a blob joined only by a faint shadow must be removed"


def test_refine_alpha_mask_keeps_a_thinly_connected_part():
    """A wing mirror or aerial joined to the body by only a few pixels must
    not be mistaken for a second, disconnected object."""
    raw = np.zeros((200, 300), dtype=np.uint8)
    raw[50:150, 20:220] = 255
    raw[60:70, 220:235] = 255
    raw[55:80, 235:255] = 255

    refined = np.array(compositing.refine_alpha_mask(Image.fromarray(raw, "L")))

    assert refined[100, 120] == 255, "the body must survive"
    assert refined[65, 245] == 255, "the thinly-connected mirror must survive too"


def test_trim_transparent_removes_the_margin():
    trimmed = compositing.trim_transparent(cutout_on_padding(pad=40))
    assert 200 <= trimmed.width <= 206
    assert 100 <= trimmed.height <= 106


def test_trim_transparent_survives_a_fully_empty_cutout():
    empty = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert compositing.trim_transparent(empty).size == (50, 50)


# ── Geometry ───────────────────────────────────────────────────────────────────

def test_contact_y_ignores_a_stray_low_pixel():
    """One column of leftover mask below the car must not lift it off the floor."""
    alpha = np.zeros((200, 200), dtype=np.uint8)
    alpha[50:150, :] = 255
    alpha[150:199, 5] = 255

    vehicle = Image.new("RGBA", (200, 200))
    vehicle.putalpha(Image.fromarray(alpha, "L"))

    assert compositing._contact_y(vehicle) < 160


def test_contact_y_reaches_into_a_softly_feathered_tyre_edge():
    height, width = 140, 200
    alpha = np.zeros((height, width), dtype=np.uint8)
    alpha[:100, :] = 255
    fade_rows = 12
    for i in range(fade_rows):
        alpha[100 + i, :] = max(0, 255 - round(255 * (i + 1) / fade_rows))
    true_visible_bottom = 100 + fade_rows - 1

    vehicle = Image.new("RGBA", (width, height))
    vehicle.putalpha(Image.fromarray(alpha, "L"))

    contact = compositing._contact_y(vehicle)
    assert contact >= true_visible_bottom - 3, (
        f"contact line ({contact}) sits too far above the tyre's actual soft "
        f"edge ({true_visible_bottom}) — this is the floating-car bug"
    )


def _cutout_with_shadow_skirt(reach: int, max_alpha: int, width=200, height=100) -> Image.Image:
    """A solid vehicle block sitting above a long, faint, gradually-fading
    trail of low alpha."""
    pad_bottom = reach + 5
    alpha = np.zeros((height + pad_bottom, width), dtype=np.uint8)
    alpha[:height, :] = 255
    for i in range(1, reach):
        alpha[height - 1 + i, :] = round(max_alpha * (1 - i / reach))

    vehicle = Image.new("RGBA", (width, height + pad_bottom))
    vehicle.putalpha(Image.fromarray(alpha, "L"))
    return vehicle


def test_contact_y_does_not_chase_a_retained_cast_shadow():
    solid_bottom = 99
    for reach, max_alpha in [(40, 60), (80, 60), (150, 80), (200, 40)]:
        vehicle = _cutout_with_shadow_skirt(reach=reach, max_alpha=max_alpha)
        contact = compositing._contact_y(vehicle)
        assert contact <= solid_bottom + compositing._CONTACT_MAX_SOFT_EXTENSION, (
            f"reach={reach} max_alpha={max_alpha}: contact ({contact}) chased the "
            f"shadow well past the capped soft extension — this floats the car"
        )


def test_shadow_capped_bottom_ignores_a_retained_cast_shadow():
    solid_bottom = 99
    for reach, max_alpha in [(40, 60), (80, 60), (150, 80), (200, 40)]:
        vehicle = _cutout_with_shadow_skirt(reach=reach, max_alpha=max_alpha)
        bottom = compositing._shadow_capped_bottom(vehicle)
        assert bottom is not None
        assert bottom <= solid_bottom + compositing._CONTACT_MAX_SOFT_EXTENSION, (
            f"reach={reach} max_alpha={max_alpha}: measured bottom ({bottom}) "
            f"chased the shadow — this shrinks the whole car"
        )


def test_shadow_capped_bottom_is_none_without_any_solid_content():
    """A cutout with nothing confidently solid has no vehicle to measure."""
    alpha = np.full((50, 50), 20, dtype=np.uint8)
    vehicle = Image.new("RGBA", (50, 50))
    vehicle.putalpha(Image.fromarray(alpha, "L"))

    assert compositing._shadow_capped_bottom(vehicle) is None


def _cutout_with_shadow_skirt_sideways(reach: int, max_alpha: int, width=100, height=200) -> Image.Image:
    """`_cutout_with_shadow_skirt`, turned ninety degrees."""
    pad_right = reach + 5
    alpha = np.zeros((height, width + pad_right), dtype=np.uint8)
    alpha[:, :width] = 255
    for i in range(1, reach):
        alpha[:, width - 1 + i] = round(max_alpha * (1 - i / reach))

    vehicle = Image.new("RGBA", (width + pad_right, height))
    vehicle.putalpha(Image.fromarray(alpha, "L"))
    return vehicle


def test_shadow_capped_side_ignores_a_retained_cast_shadow():
    """However far a sideways shadow trails, the measured right edge must
    stay near the vehicle's own solid extent."""
    solid_right = 99
    for reach, max_alpha in [(40, 60), (80, 60), (150, 80), (200, 40)]:
        vehicle = _cutout_with_shadow_skirt_sideways(reach=reach, max_alpha=max_alpha)
        right = compositing._shadow_capped_side(vehicle, leading=False)
        assert right is not None
        assert right <= solid_right + compositing._CONTACT_MAX_SOFT_EXTENSION, (
            f"reach={reach} max_alpha={max_alpha}: measured right edge ({right}) "
            f"chased the shadow — this shrinks the whole car"
        )


def test_shadow_capped_side_leading_edge_is_unaffected_by_a_trailing_shadow():
    """A shadow trailing off the right must not move the measured left edge."""
    vehicle = _cutout_with_shadow_skirt_sideways(reach=150, max_alpha=80)
    left = compositing._shadow_capped_side(vehicle, leading=True)
    assert left == 0


def test_shadow_capped_side_is_none_without_any_solid_content():
    alpha = np.full((50, 50), 20, dtype=np.uint8)
    vehicle = Image.new("RGBA", (50, 50))
    vehicle.putalpha(Image.fromarray(alpha, "L"))

    assert compositing._shadow_capped_side(vehicle, leading=False) is None
    assert compositing._shadow_capped_side(vehicle, leading=True) is None


def _add_shadow_skirt(cutout: Image.Image, reach: int, max_alpha: int) -> Image.Image:
    """Add a faint, gradually-fading shadow trail below each column's own
    existing solid content."""
    array = np.array(cutout).copy()
    alpha = array[:, :, 3]
    height, width = alpha.shape
    for x in range(width):
        solid_rows = np.flatnonzero(alpha[:, x] >= compositing._CONTACT_SOLID_ALPHA)
        if not solid_rows.size:
            continue
        bottom = int(solid_rows[-1])
        for i in range(1, reach):
            y = bottom + i
            if y >= height:
                break
            fade = max_alpha * (1 - i / reach)
            if fade > alpha[y, x]:
                alpha[y, x] = fade
                array[y, x, :3] = 30
    array[:, :, 3] = alpha
    return Image.fromarray(array, "RGBA")


def test_compose_renders_a_similar_size_whatever_a_shadow_skirt_reaches():
    """A front-on photograph with a retained cast shadow must not render
    smaller than the rest of the gallery."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    car = silhouette(1.2, height=280)

    def rendered_height(shadow_reach: int, shadow_alpha: int) -> int:
        padded = Image.new("RGBA", (car.width, car.height + shadow_reach + 50), (0, 0, 0, 0))
        padded.paste(car, (0, 0))
        if shadow_reach:
            padded = _add_shadow_skirt(padded, reach=shadow_reach, max_alpha=shadow_alpha)
        result, meta = compositing.compose(padded, backdrop_image, preset, angle="front")
        assert meta["height_normalised"] is True, (
            f"reach={shadow_reach}: fell back to fill-the-box instead of normalising"
        )
        return rendered_vehicle_height(result)

    baseline = rendered_height(0, 0)
    for reach, max_alpha in [(80, 60), (150, 80), (200, 40), (600, 60), (900, 60)]:
        shadowed = rendered_height(reach, max_alpha)
        assert shadowed >= baseline * 0.9, (
            f"reach={reach} max_alpha={max_alpha}: car rendered {shadowed}px tall "
            f"against a {baseline}px baseline — shrunk by the shadow's own reach"
        )


def test_fit_vehicle_height_clamp_uses_the_capped_height_not_the_raw_cutout():
    """Pins that the overflow clamp in `_fit_vehicle` divides by the
    shadow-capped `visible_h`, not `cutout.height`."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    car = silhouette(1.2, height=280)
    padded = Image.new("RGBA", (car.width, car.height + 950), (0, 0, 0, 0))
    padded.paste(car, (0, 0))
    padded = _add_shadow_skirt(padded, reach=900, max_alpha=60)

    result, meta = compositing.compose(padded, backdrop_image, preset, angle="front")
    assert meta["height_normalised"] is True
    assert rendered_vehicle_height(result) > 250, (
        "an extreme shadow trail still shrank the car — the clamp is reading "
        "the raw cutout height again"
    )


def _add_shadow_skirt_sideways(cutout: Image.Image, reach: int, max_alpha: int) -> Image.Image:
    """`_add_shadow_skirt`, turned ninety degrees."""
    array = np.array(cutout).copy()
    alpha = array[:, :, 3]
    height, width = alpha.shape
    for y in range(height):
        solid_cols = np.flatnonzero(alpha[y, :] >= compositing._CONTACT_SOLID_ALPHA)
        if not solid_cols.size:
            continue
        right = int(solid_cols[-1])
        for i in range(1, reach):
            x = right + i
            if x >= width:
                break
            fade = max_alpha * (1 - i / reach)
            if fade > alpha[y, x]:
                alpha[y, x] = fade
                array[y, x, :3] = 30
    array[:, :, 3] = alpha
    return Image.fromarray(array, "RGBA")


def rendered_vehicle_width(result: Image.Image) -> int:
    """Width of the car in the finished frame, found by its colour."""
    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    cols = np.where(red.any(axis=0))[0]
    return 0 if cols.size == 0 else int(cols.max() - cols.min() + 1)


def test_compose_renders_a_similar_height_whatever_a_sideways_shadow_reaches():
    """A side-on photograph with a shadow trailing off one side must not
    render smaller than the rest of the gallery."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    car = silhouette(3.2, height=220)

    def rendered_height(shadow_reach: int, shadow_alpha: int) -> int:
        padded = Image.new("RGBA", (car.width + shadow_reach + 50, car.height), (0, 0, 0, 0))
        padded.paste(car, (0, 0))
        if shadow_reach:
            padded = _add_shadow_skirt_sideways(padded, reach=shadow_reach, max_alpha=shadow_alpha)
        result, meta = compositing.compose(padded, backdrop_image, preset, angle="side")
        assert meta["height_normalised"] is True, (
            f"reach={shadow_reach}: fell back to fill-the-box instead of normalising"
        )
        return rendered_vehicle_height(result)

    baseline = rendered_height(0, 0)
    for reach, max_alpha in [(80, 60), (150, 80), (200, 40), (600, 60), (900, 60)]:
        shadowed = rendered_height(reach, max_alpha)
        assert shadowed >= baseline * 0.9, (
            f"reach={reach} max_alpha={max_alpha}: car rendered {shadowed}px tall "
            f"against a {baseline}px baseline — shrunk by the sideways shadow's own reach"
        )


def test_fit_vehicle_width_clamp_uses_the_capped_width_not_the_raw_cutout():
    """Pins that the overflow clamp in `_fit_vehicle` divides by the
    shadow-capped `visible_w`, not `cutout.width`."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    car = silhouette(3.2, height=220)
    padded = Image.new("RGBA", (car.width + 950, car.height), (0, 0, 0, 0))
    padded.paste(car, (0, 0))
    padded = _add_shadow_skirt_sideways(padded, reach=900, max_alpha=60)

    result, meta = compositing.compose(padded, backdrop_image, preset, angle="side")
    assert meta["height_normalised"] is True
    assert rendered_vehicle_height(result) > 190, (
        "an extreme sideways shadow trail still shrank the car — the width "
        "clamp is reading the raw cutout width again"
    )


def test_visible_bounds_ignores_transparent_margin():
    assert compositing._visible_bounds(cutout_on_padding(pad=40)) == (40, 40, 240, 140)


def test_dealer_backdrop_keeps_its_own_resolution():
    result, meta = compositing.compose(cutout_on_padding(), backdrop(1600, 1200))
    assert result.size == (1600, 1200)
    assert meta["output_size"] == {"width": 1600, "height": 1200}


def test_oversized_backdrop_is_capped():
    result, _ = compositing.compose(cutout_on_padding(), backdrop(4000, 3000))
    assert result.width == compositing.MAX_CANVAS_WIDTH
    assert result.height == 1800


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

    assert abs(ys.max() - canvas_h * 0.84) < canvas_h * 0.03


def test_custom_ground_y_ratio_moves_the_contact_point():
    """APA-138: a dealer's own measured ground line must actually be used,
    not just accepted and ignored."""
    canvas_h = 1200
    measured = replace(compositing.DEALER_BACKDROP, ground_y_ratio=0.65)
    result, _ = compositing.compose(cutout_on_padding(), backdrop(1600, canvas_h), measured)

    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    ys = np.where(red.any(axis=1))[0]

    assert abs(ys.max() - canvas_h * 0.65) < canvas_h * 0.03


def test_different_ground_y_ratios_land_in_different_places():
    """Two backdrops with different measured floors must not render the
    vehicle at the same height."""
    high = replace(compositing.DEALER_BACKDROP, ground_y_ratio=0.55)
    low = replace(compositing.DEALER_BACKDROP, ground_y_ratio=0.90)

    def bottom_of_car(preset):
        result, _ = compositing.compose(cutout_on_padding(), backdrop(1600, 1200), preset)
        pixels = np.array(result.convert("RGB"))
        red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
        ys = np.where(red.any(axis=1))[0]
        return ys.max()

    assert bottom_of_car(low) - bottom_of_car(high) > 300, (
        "a 0.35 canvas-height difference in ground_y_ratio should move the "
        "vehicle's contact point by a comparable number of pixels"
    )


def test_unconfigured_backdrop_still_uses_the_generic_guess():
    """None (an unmeasured backdrop) must keep exactly the pre-APA-138 behaviour."""
    canvas_h = 1200
    explicit_default = replace(compositing.DEALER_BACKDROP, ground_y_ratio=None)
    with pytest.raises(TypeError):
        compositing.compose(cutout_on_padding(), backdrop(1600, canvas_h), explicit_default)


def test_low_ground_line_does_not_crop_the_vehicle_off_the_top():
    """APA-138 follow-up: a low ground line combined with a wide canvas must
    not size the vehicle taller than the room available above it."""
    canvas_w, canvas_h = 1774, 887
    low_floor = replace(compositing.DEALER_BACKDROP, ground_y_ratio=0.37)
    result, _ = compositing.compose(cutout_on_padding(), backdrop(canvas_w, canvas_h), low_floor)

    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    ys = np.where(red.any(axis=1))[0]

    assert ys.min() > 0, "the vehicle's roof was cropped off above the canvas"
    assert ys.max() <= canvas_h * 0.37 + 2, "it must still land on the configured ground line"


def test_shadow_blur_scales_with_vehicle_size():
    """Shadow blur must scale with the vehicle's own pixel height, not stay
    a fixed number of pixels."""
    small_alpha = Image.new("L", (400, 200), 255)
    big_alpha = Image.new("L", (400, 2000), 255)

    small_shadow, _ = compositing._shadows(small_alpha, vehicle_x=0, ground_y=200)[1]
    big_shadow, _ = compositing._shadows(big_alpha, vehicle_x=0, ground_y=2000)[1]

    assert big_shadow.width - small_shadow.width > 100, (
        "a taller vehicle silhouette should produce a visibly more blurred "
        "(and so wider-padded) contact shadow, not an identically-blurred one"
    )


def test_shadow_darkens_the_floor_beneath_the_vehicle():
    plain = backdrop(1600, 1200, colour=(200, 200, 205))
    result, _ = compositing.compose(cutout_on_padding(), plain)

    pixels = np.array(result.convert("RGB")).astype(np.int16)
    band = pixels[1030:1060, 300:1300]
    assert band.mean() < 200, "expected a shadow, floor is unchanged"


# ── Composite must not fall over on awkward sizes ──────────────────────────────

@pytest.mark.parametrize("size", [(320, 240), (400, 300), (2000, 400), (300, 900)])
def test_small_and_extreme_backdrops_do_not_raise(size):
    """Shadows padded by twice the blur radius can push the paste
    destination negative or past the edge on a small backdrop."""
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
    scene = backdrop(400, 300, colour=(40, 40, 60))

    matched = compositing.match_colour(vehicle, scene, 50, 50)

    before = np.array(vehicle.convert("RGB")).astype(np.int16)
    after = np.array(matched.convert("RGB")).astype(np.int16)
    shift = np.abs(after - before).mean()

    assert shift > 0, "colour matching did nothing"
    assert shift < 40, "colour matching repainted the car"


def test_colour_match_pulls_contrast_towards_the_scene():
    """Two photos can share a mean tone and still read as lit completely
    differently, so contrast has to move independently of tone."""
    vehicle = Image.new("RGBA", (200, 100), (60, 60, 90, 255))
    ImageDraw.Draw(vehicle).rectangle((0, 40, 200, 60), fill=(160, 160, 190, 255))
    flat_scene = backdrop(400, 300, colour=(90, 90, 110))

    before_std = np.array(vehicle.convert("RGB")).astype(np.float32).std()
    matched = compositing.match_colour(vehicle, flat_scene, 50, 50)
    after_std = np.array(matched.convert("RGB")).astype(np.float32).std()

    assert after_std < before_std, "contrast should shrink towards the flatter backdrop"


def test_colour_match_skips_contrast_on_a_flat_cutout():
    """A solid-colour cutout has a lightness spread of zero, so contrast
    matching must fall through to the plain mean-shift without dividing by zero."""
    vehicle = block(200, 100, colour=(180, 40, 40))
    scene = backdrop(400, 300, colour=(40, 40, 60))

    matched = compositing.match_colour(vehicle, scene, 50, 50)
    after = np.array(matched.convert("RGB")).astype(np.float32)
    assert after.reshape(-1, 3).std(axis=0).max() < 1.0


def test_colour_match_on_an_empty_cutout_is_a_no_op():
    empty = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert compositing.match_colour(empty, backdrop(200, 200), 0, 0) is empty


def two_tone_backdrop(width=1600, height=1200, wall=(230, 230, 235), floor=(40, 40, 40)):
    """A bright wall over the top 35% of the canvas, a dark floor below it."""
    scene = Image.new("RGBA", (width, height), (*floor, 255))
    ImageDraw.Draw(scene).rectangle((0, 0, width, round(height * 0.35)), fill=(*wall, 255))
    return scene


def test_ground_placement_reads_the_wall_not_the_floor_behind_the_vehicle():
    """A 'ground' placement must read the wall band near the top of the
    canvas for lighting, not the dark floor behind a standing vehicle."""
    vehicle = block(200, 100, colour=(100, 100, 100))
    scene = two_tone_backdrop(wall=(230, 230, 235), floor=(40, 40, 40))

    matched = compositing.match_colour(vehicle, scene, 700, 1000, placement="ground")
    before = np.array(vehicle.convert("RGB")).astype(np.float32).mean()
    after = np.array(matched.convert("RGB")).astype(np.float32).mean()

    assert after > before, "a 'ground' vehicle should move towards the bright wall, not the dark floor behind it"


def test_center_placement_still_reads_the_region_behind_the_vehicle():
    """Default placement samples the local patch, not the ambient wall band."""
    vehicle = block(200, 100, colour=(100, 100, 100))
    scene = two_tone_backdrop(wall=(230, 230, 235), floor=(40, 40, 40))

    matched = compositing.match_colour(vehicle, scene, 700, 1000)
    before = np.array(vehicle.convert("RGB")).astype(np.float32).mean()
    after = np.array(matched.convert("RGB")).astype(np.float32).mean()

    assert after < before, "default placement should move towards the region behind it, not the wall band"


# ── Size consistency across angles ─────────────────────────────────────────────

CAR_ASPECTS = {
    "side": 3.13,
    "front_quarter": 2.40,
    "rear_quarter": 2.40,
    "front": 1.20,
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
    """The regression the height normalisation exists for: the head-on shot
    used to render roughly twice the height of the side-on one."""
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


def test_studio_full_renders_a_larger_car_than_the_original_budget():
    """Regression pin for the size bump on STUDIO_FULL (vehicle_width_ratio
    0.86 -> 0.90)."""
    result, _ = compositing.compose(
        car_at_aspect(CAR_ASPECTS["side"]), backdrop(2000, 1500),
        compositing.STUDIO_FULL, angle="side",
    )
    height = rendered_vehicle_height(result)
    assert height > 270, f"car should render taller than the pre-bump budget: {height}"

    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    columns = np.where(red.any(axis=0))[0]
    platform_left = round(1280 * compositing.STUDIO_FULL.platform_box[0])
    platform_right = round(1280 * compositing.STUDIO_FULL.platform_box[2])
    assert columns.min() >= platform_left and columns.max() <= platform_right, (
        "the bigger car must still stay on the measured platform, not overhang it"
    )


def test_fill_the_box_scaling_would_fail_this():
    """Guards the guard: the old fill-the-box rule must still produce the
    size spread this fix claims to have solved."""
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


# ── Backdrop exposure ────────────────────────────────────────────────────────

def test_backdrop_exposure_is_a_flat_multiplier():
    canvas = Image.new("RGBA", (10, 10), (200, 100, 50, 255))
    dimmed = compositing._apply_backdrop_exposure(canvas, 0.5)
    assert dimmed.getpixel((5, 5)) == (100, 50, 25, 255)


def test_backdrop_exposure_of_one_is_a_no_op():
    canvas = Image.new("RGBA", (10, 10), (200, 100, 50, 255))
    assert compositing._apply_backdrop_exposure(canvas, 1.0) is canvas


def test_backdrop_exposure_clamps_instead_of_wrapping():
    canvas = Image.new("RGBA", (4, 4), (200, 200, 200, 255))
    brightened = compositing._apply_backdrop_exposure(canvas, 2.0)
    assert brightened.getpixel((0, 0)) == (255, 255, 255, 255)


def test_studio_backdrop_is_dimmer_than_the_source_asset():
    scene = backdrop(2000, 1500, colour=(220, 220, 220))
    studio, _ = compositing.compose(car_at_aspect(3.13), scene, compositing.STUDIO_FULL)
    dealer, _ = compositing.compose(car_at_aspect(3.13), scene)

    corner = slice(0, 40)
    studio_corner = np.array(studio.convert("RGB"))[corner, corner].astype(np.float32)
    dealer_corner = np.array(dealer.convert("RGB"))[corner, corner].astype(np.float32)

    assert studio_corner.mean() < dealer_corner.mean() * 0.95, (
        "STUDIO_FULL's backdrop_exposure did not dim the wall"
    )


def test_dealer_backdrop_keeps_its_own_brightness():
    """An unmeasured dealer upload is not darkened just because it is bright."""
    scene = backdrop(1600, 1200, colour=(150, 150, 150))
    result, _ = compositing.compose(car_at_aspect(3.13), scene)
    corner = np.array(result.convert("RGB"))[0:20, 0:20]
    assert corner.mean() == pytest.approx(150, abs=1)


# ── Reflection ─────────────────────────────────────────────────────────────────

_REFLECTING_STUDIO_FULL = replace(compositing.STUDIO_FULL, reflection_strength=0.30)


def test_reflection_only_on_a_surface_we_measured():
    """A dealer's backdrop may not be polished, so a reflection is limited
    to the platform whose finish we can actually see."""
    _, studio = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), _REFLECTING_STUDIO_FULL
    )
    _, dealer = compositing.compose(car_at_aspect(3.13), backdrop(1600, 1200))
    _, closeup = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_CLOSEUP
    )

    assert studio["reflection_applied"] is True
    assert dealer["reflection_applied"] is False, "we do not know a dealer's floor is polished"
    assert closeup["reflection_applied"] is False, "a wall-backed close-up has no floor"


def test_studio_full_ships_with_the_reflection_off():
    """Pin the current shipped default: reflection is off on STUDIO_FULL
    until `_contact_y`'s ground line is fixed."""
    _, meta = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_FULL
    )
    assert compositing.STUDIO_FULL.reflection_strength == 0.0
    assert meta["reflection_applied"] is False


def test_reflection_darkens_the_platform_below_the_car():
    car = car_at_aspect(3.13)
    scene = backdrop(2000, 1500)

    lit, _ = compositing.compose(car, scene, _REFLECTING_STUDIO_FULL)
    plain_preset = replace(_REFLECTING_STUDIO_FULL, reflection_strength=0.0)
    unlit, meta = compositing.compose(car, scene, plain_preset)
    assert meta["reflection_applied"] is False

    contact = round(960 * compositing.STUDIO_FULL.platform_contact_y_ratio)
    band = slice(contact + 4, contact + 40)
    with_reflection = np.array(lit.convert("RGB"))[band, 400:900].astype(np.int16)
    without = np.array(unlit.convert("RGB"))[band, 400:900].astype(np.int16)

    assert with_reflection.mean() < without.mean(), "reflection did not darken the floor"


def test_reflection_stays_on_the_platform():
    """Clipped to the ellipse: a mirror image running off the base onto the
    showroom floor is worse than none at all."""
    result, _ = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), _REFLECTING_STUDIO_FULL
    )
    bare, _ = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500),
        replace(_REFLECTING_STUDIO_FULL, reflection_strength=0.0),
    )
    lit = np.array(result.convert("RGB")).astype(np.int16)
    unlit = np.array(bare.convert("RGB")).astype(np.int16)
    difference = np.abs(lit - unlit).sum(axis=2)

    changed_rows = np.where((difference > 6).any(axis=1))[0]
    if changed_rows.size:
        platform_top = round(960 * compositing.STUDIO_FULL.platform_box[1])
        assert changed_rows.min() >= platform_top - 2, (
            f"reflection reached row {changed_rows.min()}, above the platform at {platform_top}"
        )


def silhouette(aspect: float, height: int = 520) -> Image.Image:
    """A car-shaped cutout rather than a rectangle, wider than its nominal
    aspect once wheels and mirrors are in frame."""
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
    """The regression the rectangle test missed: a side-on silhouette
    exceeding the width limit by a hair used to fall all the way back to
    fill-the-box."""
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
    """A car overhanging the base reads as floating, which is the failure
    the platform was measured to avoid."""
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


def _lopsided_silhouette(aspect, height=520, bulge_frac=0.45):
    """A side-shaped cutout carrying extra opaque mass in its own right
    third, without widening its outer bounding box."""
    car = silhouette(aspect, height=height)
    draw = ImageDraw.Draw(car)
    w, h = car.size
    bulge_w = int(w * bulge_frac)
    draw.rectangle(
        (w - bulge_w, int(h * 0.1), w - int(w * 0.03), int(h * 0.9)),
        fill=(180, 40, 40, 255),
    )
    return car


def test_vehicle_position_keeps_a_skewed_car_on_the_platform():
    """A side-on car close to the platform's own width budget must not
    render with one end hanging off the edge after the mass-skew correction."""
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    width = preset.output_size[0]
    left_edge = width * preset.platform_box[0]
    right_edge = width * preset.platform_box[2]

    car = _lopsided_silhouette(3.3)
    assert compositing._mass_skew(car) > 0.05, "fixture is not actually skewed"

    result, meta = compositing.compose(
        car, backdrop_image, preset, angle="front_quarter", angle_confidence=0.9
    )
    assert meta["height_normalised"] is True

    pixels = np.array(result.convert("RGB"))
    carpix = (pixels[:, :, 0] > 110) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
    columns = np.where(carpix.any(axis=0))[0]
    assert columns.min() >= left_edge - 6, (
        f"skewed car overhangs the platform on the left ({columns.min()} < {left_edge})"
    )
    assert columns.max() <= right_edge + 6, (
        f"skewed car overhangs the platform on the right ({columns.max()} > {right_edge})"
    )


# ── Levelling ──────────────────────────────────────────────────────────────────

def tilted_car(tilt_px: float, width: int = 420) -> Image.Image:
    """A body with two dark wheels, one `tilt_px` lower than the other."""
    body_top, body_bottom, wheel = 60, 180, 40
    pad = max(0, round(tilt_px)) + 10
    image = Image.new("RGBA", (width, body_bottom + wheel + pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, body_top, width - 40, body_bottom), fill=(30, 60, 150, 255))
    left_centre = (90, body_bottom)
    right_centre = (width - 90, body_bottom + tilt_px)
    for cx, cy in (left_centre, right_centre):
        draw.ellipse((cx - wheel, cy - wheel, cx + wheel, cy + wheel), fill=(15, 15, 15, 255))
    return image


def wheel_bottoms(image: Image.Image) -> list[float]:
    """The (x, y+radius) contact point of every wheel `_wheel_contacts` finds."""
    return sorted(
        (cx, cy + r) for cx, cy, r in compositing._wheel_contacts(image)
    )


def test_wheel_contacts_finds_both_wheels_of_a_level_car():
    contacts = compositing._wheel_contacts(tilted_car(tilt_px=0))
    assert len(contacts) == 2


def test_level_vehicle_leaves_an_already_level_car_alone():
    car = tilted_car(tilt_px=0)
    levelled, angle = compositing._level_vehicle(car, "front")
    assert angle is None
    assert levelled is car


def test_level_vehicle_straightens_a_tilted_car():
    """A car whose near wheel renders lower than its far one must come out level."""
    car = tilted_car(tilt_px=25)
    before = wheel_bottoms(car)
    before_gap = abs(before[0][1] - before[1][1])
    assert before_gap > 15, "fixture is not actually tilted"

    levelled, angle = compositing._level_vehicle(car, "front")
    assert angle is not None and angle > 0

    after = wheel_bottoms(levelled)
    after_gap = abs(after[0][1] - after[1][1])
    assert after_gap < 2, f"wheels are still {after_gap:.1f}px apart after levelling"


@pytest.mark.parametrize("angle", ["front", "rear", "side"])
def test_level_vehicle_straightens_on_every_safe_angle(angle):
    car = tilted_car(tilt_px=25)
    levelled, applied = compositing._level_vehicle(car, angle)
    assert applied is not None and applied > 0
    after = wheel_bottoms(levelled)
    assert abs(after[0][1] - after[1][1]) < 2


@pytest.mark.parametrize("angle", ["front_quarter", "rear_quarter", None, "nonsense-label"])
def test_level_vehicle_declines_on_an_unsafe_angle(angle):
    car = tilted_car(tilt_px=25)
    levelled, applied = compositing._level_vehicle(car, angle)
    assert applied is None
    assert levelled is car


def test_level_vehicle_declines_an_implausible_tilt():
    """A tilt past MAX_LEVEL_CORRECTION_DEGREES is more likely a bad circle
    match than a genuine one to correct."""
    car = tilted_car(tilt_px=60)
    levelled, angle = compositing._level_vehicle(car, "front")
    assert angle is None
    assert levelled is car


# ── Levelling: confidence gate ──────────────────────────────────────────────

def test_level_vehicle_declines_a_safe_angle_at_low_confidence():
    car = tilted_car(tilt_px=25)
    levelled, angle = compositing._level_vehicle(
        car, "rear", angle_confidence=compositing.LEVELLING_MIN_CONFIDENCE - 0.01
    )
    assert angle is None
    assert levelled is car


def test_level_vehicle_still_levels_a_safe_angle_at_high_confidence():
    """The gate must not swallow the feature it is protecting: a label the
    classifier was genuinely sure of still levels."""
    car = tilted_car(tilt_px=25)
    levelled, angle = compositing._level_vehicle(
        car, "rear", angle_confidence=compositing.LEVELLING_MIN_CONFIDENCE + 0.1
    )
    assert angle is not None and angle > 0
    assert levelled is not car


def test_level_vehicle_trusts_the_label_when_confidence_is_not_given():
    """A caller that does not know the classifier's confidence keeps the
    original behaviour of trusting the angle label alone."""
    car = tilted_car(tilt_px=25)
    levelled, angle = compositing._level_vehicle(car, "rear")
    assert angle is not None and angle > 0
    assert levelled is not car


def test_compose_forwards_angle_confidence_to_levelling():
    """`compose()` must actually pass `angle_confidence` through to `_level_vehicle`."""
    car = tilted_car(tilt_px=25)
    bg = backdrop(1600, 1200)

    _, low = compositing.compose(
        car, bg, angle="rear",
        angle_confidence=compositing.LEVELLING_MIN_CONFIDENCE - 0.01,
    )
    assert low["levelled_degrees"] is None

    _, high = compositing.compose(
        car, bg, angle="rear",
        angle_confidence=compositing.LEVELLING_MIN_CONFIDENCE + 0.1,
    )
    assert high["levelled_degrees"] is not None and high["levelled_degrees"] > 0


# ── Wheel-perspective contact capping ───────────────────────────────────────

def perspective_car(
    near_radius: float, far_radius: float, near_y: float, far_y: float,
    width: int = 900, body_bottom: int = 420, body_top: int = 140,
) -> Image.Image:
    """Like `tilted_car`, but the two wheels differ in radius as well as
    height, the way genuine camera perspective renders a near/far pair."""
    pad = round(max(near_y, far_y, 0)) + round(max(near_radius, far_radius)) + 10
    image = Image.new("RGBA", (width, body_bottom + pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, body_top, width - 80, body_bottom), fill=(30, 60, 150, 255))
    far_centre = (170, body_bottom + far_y)
    near_centre = (width - 170, body_bottom + near_y)
    for (cx, cy), r in ((far_centre, far_radius), (near_centre, near_radius)):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(15, 15, 15, 255))
    return image


def test_contact_y_no_longer_grounds_to_the_shallower_wheel():
    """`_wheel_grounded_contact_cap` is no longer consulted by `_contact_y`."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    contacts = wheel_bottoms(car)
    assert len(contacts) == 2, "fixture must produce two detectable wheels"
    shallow = min(c for _, c in contacts)
    deep = max(c for _, c in contacts)
    assert deep - shallow > 40, "fixture does not actually disagree enough"

    contact = compositing._contact_y(car, "side")
    assert contact > shallow + 2, (
        "the wheel cap fired — it must no longer be consulted by _contact_y"
    )


def test_contact_y_ignores_the_wheel_cap_regardless_of_angle_or_confidence():
    """Pins the 'no cap' behaviour across every angle/confidence combination."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    deep = max(c for _, c in wheel_bottoms(car))

    for angle, confidence in (
        ("front_quarter", None),
        ("side", compositing.LEVELLING_MIN_CONFIDENCE - 0.01),
        ("side", compositing.LEVELLING_MIN_CONFIDENCE + 0.1),
        ("side", None),
    ):
        contact = compositing._contact_y(car, angle, angle_confidence=confidence)
        assert contact > deep - 5, (
            f"wheel cap fired for angle={angle!r} confidence={confidence!r}"
        )


def test_wheel_grounded_contact_cap_declines_an_implausible_gap(monkeypatch):
    """A gap this large relative to the vehicle's own height is more likely
    a bad circle match than a real photograph."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    monkeypatch.setattr(
        compositing, "_wheel_contacts",
        lambda vehicle: [(150.0, 40.0, 20.0), (700.0, 400.0, 70.0)],
    )
    assert compositing._wheel_grounded_contact_cap(car) is None


def test_wheel_grounded_contact_cap_is_none_without_two_wheels():
    blank = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    assert compositing._wheel_grounded_contact_cap(blank) is None


def test_wheel_grounded_contact_cap_ignores_two_detections_too_close_together(monkeypatch):
    """Two circles a hair's width apart are more likely the same wheel
    matched twice than a genuine front-and-rear pair."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    monkeypatch.setattr(
        compositing, "_wheel_contacts",
        lambda vehicle: [(150.0, 400.0, 55.0), (150.0 + car.width * 0.05, 400.0, 55.0)],
    )
    assert compositing._wheel_grounded_contact_cap(car) is None


# ── Quarter-angle ground recession ────────────────────────────────────────────

def test_recede_quarter_ground_closes_the_full_gap_on_a_safe_angle():
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    before = wheel_bottoms(car)
    before_gap = abs(before[0][1] - before[1][1])
    assert before_gap > 40, "fixture does not actually disagree enough"

    warped, correction = compositing._recede_quarter_ground(
        car, "front_quarter", angle_confidence=0.9
    )
    assert correction is not None and correction > 0
    assert warped is not car

    after = wheel_bottoms(warped)
    after_gap = abs(after[0][1] - after[1][1])
    assert after_gap < before_gap * 0.15, (
        f"gap did not close enough: {before_gap:.1f}px before, {after_gap:.1f}px after"
    )
    expected = before_gap * (1 - compositing._QUARTER_RECEDE_CORRECTION_FRACTION)
    assert abs(after_gap - expected) < before_gap * 0.15


def test_recede_quarter_ground_keeps_the_far_wheel_round():
    """The far wheel must translate as a rigid shift, not shear into an oval."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    before_radii = sorted(r for _, _, r in compositing._wheel_contacts(car))

    warped, _ = compositing._recede_quarter_ground(car, "front_quarter", angle_confidence=0.9)
    after_radii = sorted(r for _, _, r in compositing._wheel_contacts(warped))

    assert len(after_radii) == 2, "warp must not destroy either wheel's detectability"
    for before_r, after_r in zip(before_radii, after_radii):
        assert abs(after_r - before_r) < before_r * 0.1


def test_recede_quarter_ground_leaves_the_near_wheel_in_place():
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    near_before = max(wheel_bottoms(car), key=lambda p: p[0])

    warped, _ = compositing._recede_quarter_ground(car, "front_quarter", angle_confidence=0.9)
    near_after = max(wheel_bottoms(warped), key=lambda p: p[0])

    assert abs(near_after[0] - near_before[0]) < 6
    assert abs(near_after[1] - near_before[1]) < 6


@pytest.mark.parametrize("angle", ["front", "rear", "side", None, "unknown"])
def test_recede_quarter_ground_declines_outside_safe_angles(angle):
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    warped, correction = compositing._recede_quarter_ground(car, angle, angle_confidence=0.9)
    assert correction is None
    assert warped is car


@pytest.mark.parametrize("angle", ["front_quarter", "rear_quarter"])
def test_recede_quarter_ground_applies_on_both_quarter_angles(angle):
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    _, correction = compositing._recede_quarter_ground(car, angle, angle_confidence=0.9)
    assert correction is not None and correction > 0


def test_recede_quarter_ground_declines_at_low_confidence():
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    warped, correction = compositing._recede_quarter_ground(
        car, "front_quarter",
        angle_confidence=compositing.LEVELLING_MIN_CONFIDENCE - 0.01,
    )
    assert correction is None
    assert warped is car


def test_recede_quarter_ground_trusts_the_label_when_confidence_is_not_given():
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    _, correction = compositing._recede_quarter_ground(car, "front_quarter")
    assert correction is not None and correction > 0


def test_recede_quarter_ground_declines_without_two_wheels():
    blank = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    warped, correction = compositing._recede_quarter_ground(
        blank, "front_quarter", angle_confidence=0.9
    )
    assert correction is None
    assert warped is blank


def test_recede_quarter_ground_declines_a_negligible_gap():
    car = perspective_car(near_radius=60, far_radius=60, near_y=0, far_y=0)
    _, correction = compositing._recede_quarter_ground(car, "front_quarter", angle_confidence=0.9)
    assert correction is None


def test_recede_quarter_ground_declines_an_implausible_gap(monkeypatch):
    """A gap this large relative to the vehicle's own height is more likely
    a bad circle match than a real photograph."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    monkeypatch.setattr(
        compositing, "_wheel_contacts",
        lambda vehicle: [(150.0, 40.0, 20.0), (700.0, 400.0, 70.0)],
    )
    _, correction = compositing._recede_quarter_ground(car, "front_quarter", angle_confidence=0.9)
    assert correction is None


def test_recede_quarter_ground_ignores_two_detections_too_close_together(monkeypatch):
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    monkeypatch.setattr(
        compositing, "_wheel_contacts",
        lambda vehicle: [(150.0, 400.0, 55.0), (150.0 + car.width * 0.05, 400.0, 55.0)],
    )
    _, correction = compositing._recede_quarter_ground(car, "front_quarter", angle_confidence=0.9)
    assert correction is None


def test_compose_reports_the_quarter_ground_correction():
    """The correction this function makes must reach the job record, and
    must not fire on angles it should not touch."""
    car = perspective_car(near_radius=70, far_radius=55, near_y=0, far_y=-70)
    bg = backdrop(1600, 1200)

    _, quarter = compositing.compose(car, bg, angle="front_quarter", angle_confidence=0.9)
    assert quarter["quarter_ground_correction_px"] is not None
    assert quarter["quarter_ground_correction_px"] > 0

    _, front = compositing.compose(car, bg, angle="front", angle_confidence=0.9)
    assert front["quarter_ground_correction_px"] is None


# ── Wheel gap patching ───────────────────────────────────────────────────────

def _trim_wheel_bottom(image: Image.Image, cx: int, rows: int) -> Image.Image:
    """Clear a `rows`-tall band of alpha across the wheel centred at `cx`,
    simulating a segmentation gap."""
    array = np.array(image)
    alpha = array[:, :, 3]
    opaque_rows = np.flatnonzero(alpha[:, cx] >= 32)
    bottom = int(opaque_rows[-1])
    x0, x1 = max(0, cx - 45), cx + 45
    alpha[bottom - rows + 1 : bottom + 1, x0:x1] = 0
    array[:, :, 3] = alpha
    return Image.fromarray(array, "RGBA")


def _column_bottom(image: Image.Image, x: int) -> int | None:
    """The lowest row at column `x` where alpha is visible, matching the
    threshold `_patch_wheel_gaps` itself reads by."""
    rows = np.flatnonzero(np.array(image.getchannel("A"))[:, x] >= 32)
    return int(rows[-1]) if rows.size else None


def test_patch_wheel_gaps_fills_a_trimmed_wheel():
    """A wheel missing its bottom few rows of alpha must come back reaching
    about as far down as its untouched twin."""
    car = tilted_car(tilt_px=0)
    left_cx, right_cx = 90, 420 - 90
    original_bottom = _column_bottom(car, left_cx)

    trimmed = _trim_wheel_bottom(car, left_cx, rows=10)
    assert _column_bottom(trimmed, left_cx) < original_bottom - 5, (
        "fixture is not actually missing pixels"
    )

    patched = compositing._patch_wheel_gaps(trimmed)
    left_after = _column_bottom(patched, left_cx)
    right_after = _column_bottom(patched, right_cx)
    assert left_after >= original_bottom - 2, (
        f"trimmed wheel still falls short of the ground: {left_after} vs {original_bottom}"
    )
    assert abs(left_after - right_after) < 3, (
        f"patched wheel does not land level with its untouched twin: {left_after} vs {right_after}"
    )


def test_patch_wheel_gaps_declines_a_gap_past_the_allowed_fraction():
    """Past `_MAX_WHEEL_PATCH_FRACTION` of the wheel's own radius, a missing
    chunk must not be patched."""
    car = tilted_car(tilt_px=0)
    left_cx = 90
    original_bottom = _column_bottom(car, left_cx)

    trimmed = _trim_wheel_bottom(car, left_cx, rows=25)
    before = _column_bottom(trimmed, left_cx)

    patched = compositing._patch_wheel_gaps(trimmed)
    after = _column_bottom(patched, left_cx)
    assert after < original_bottom - 15, (
        f"declined gap was filled anyway: {after} vs original {original_bottom}"
    )
    assert after <= before + 3, "declined wheel moved as if it had been patched"


def test_patch_wheel_gaps_makes_only_a_small_correction_on_an_already_level_car():
    """An already-flush car should come back essentially unchanged."""
    car = tilted_car(tilt_px=0)
    left_cx, right_cx = 90, 420 - 90
    before_left, before_right = _column_bottom(car, left_cx), _column_bottom(car, right_cx)

    patched = compositing._patch_wheel_gaps(car)
    after_left, after_right = _column_bottom(patched, left_cx), _column_bottom(patched, right_cx)

    assert abs(after_left - before_left) <= 4
    assert abs(after_right - before_right) <= 4
    assert abs(after_left - after_right) < 3, "patch broke symmetry on a level car"


def test_patch_wheel_gaps_leaves_a_car_with_no_detectable_wheels_alone():
    """No circles found means nothing to ground a patch against, so the
    image must be left untouched."""
    body = Image.new("RGBA", (200, 150), (0, 0, 0, 0))
    ImageDraw.Draw(body).rectangle((20, 20, 180, 130), fill=(100, 100, 200, 255))
    assert compositing._wheel_contacts(body) == []

    result = compositing._patch_wheel_gaps(body)
    assert result is body


def test_compose_levels_a_tilted_vehicle_and_reports_it():
    result, meta = compositing.compose(
        tilted_car(tilt_px=25), backdrop(1600, 1200), angle="front"
    )
    assert meta["levelled_degrees"] is not None and meta["levelled_degrees"] > 0

    pixels = np.array(result.convert("RGB"))
    dark = (pixels[:, :, 0] < 60) & (pixels[:, :, 1] < 60) & (pixels[:, :, 2] < 60)
    midpoint = pixels.shape[1] // 2
    left_bottom = np.where(dark[:, :midpoint].any(axis=1))[0].max()
    right_bottom = np.where(dark[:, midpoint:].any(axis=1))[0].max()
    assert abs(int(left_bottom) - int(right_bottom)) < 8, (
        f"wheels do not land level in the final composite: {left_bottom} vs {right_bottom}"
    )


def test_compose_does_not_report_levelling_for_an_already_level_car():
    _, meta = compositing.compose(
        tilted_car(tilt_px=0), backdrop(1600, 1200), angle="front"
    )
    assert meta["levelled_degrees"] is None


def test_compose_does_not_level_a_quarter_angle_shot_even_when_tilted():
    """`compose` itself must not rotate a quarter-angle vehicle to force its
    wheels level."""
    _, meta = compositing.compose(
        tilted_car(tilt_px=25), backdrop(1600, 1200), angle="front_quarter"
    )
    assert meta["levelled_degrees"] is None


# ── Recognising a dealer backdrop as a bundled studio scene ────────────────────

def test_phash_of_the_bundled_studio_asset_matches_itself():
    loaded = compositing.load_studio_backdrop("studio_full")
    assert loaded is not None, "studio-full.png is missing from assets"
    image, _ = loaded
    assert compositing._hamming(compositing._phash(image), compositing._phash(image)) == 0


def test_match_studio_backdrop_recognises_an_unmodified_copy():
    loaded = compositing.load_studio_backdrop("studio_full")
    assert loaded is not None, "studio-full.png is missing from assets"
    image, _ = loaded
    match = compositing.match_studio_backdrop(image)
    assert match is compositing.STUDIO_FULL


def test_match_studio_backdrop_survives_a_resize_and_jpeg_recompression():
    """A dealer's upload flow does not preserve the exact bytes; a resize
    and JPEG re-encode must still be recognised."""
    import io

    loaded = compositing.load_studio_backdrop("studio_full")
    assert loaded is not None, "studio-full.png is missing from assets"
    image, _ = loaded

    resized = image.convert("RGB").resize((900, 675))
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    recompressed = Image.open(buffer).convert("RGBA")

    match = compositing.match_studio_backdrop(recompressed)
    assert match is compositing.STUDIO_FULL


def test_match_studio_backdrop_tells_the_two_bundled_scenes_apart():
    closeup_loaded = compositing.load_studio_backdrop("studio_closeup")
    assert closeup_loaded is not None, "studio-closeup.png is missing from assets"
    image, _ = closeup_loaded
    match = compositing.match_studio_backdrop(image)
    assert match is compositing.STUDIO_CLOSEUP


def test_match_studio_backdrop_declines_an_unrelated_photograph():
    """An ordinary dealer backdrop must fall through untouched."""
    unrelated = backdrop(1600, 1200, colour=(80, 120, 60))
    assert compositing.match_studio_backdrop(unrelated) is None


def test_place_on_backdrop_uses_the_measured_preset_for_a_recognised_scene():
    """End-to-end: a dealer backdrop that happens to be the studio scene
    should compose exactly as STUDIO_FULL does."""
    loaded = compositing.load_studio_backdrop("studio_full")
    assert loaded is not None, "studio-full.png is missing from assets"
    studio_image, _ = loaded

    matched_preset = compositing.match_studio_backdrop(studio_image)
    result, meta = compositing.compose(
        car_at_aspect(CAR_ASPECTS["side"]), studio_image, matched_preset, angle="side"
    )
    assert meta["output_size"] == {"width": 1280, "height": 960}

    pixels = np.array(result.convert("RGB"))
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100)
    columns = np.where(red.any(axis=0))[0]
    platform_left = round(1280 * compositing.STUDIO_FULL.platform_box[0])
    platform_right = round(1280 * compositing.STUDIO_FULL.platform_box[2])
    assert columns.min() >= platform_left and columns.max() <= platform_right, (
        "a recognised studio backdrop must still clamp to the measured platform"
    )
