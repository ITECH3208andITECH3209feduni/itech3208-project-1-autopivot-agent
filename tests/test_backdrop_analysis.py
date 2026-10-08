import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

import backdrop_analysis
import compositing


WIDTH, HEIGHT = 1200, 900


def room(vanishing_x=600, vanishing_y=400, size=(WIDTH, HEIGHT)):
    """A drawn room whose lines converge on a known point."""
    canvas = Image.new("RGB", size, (200, 200, 205))
    draw = ImageDraw.Draw(canvas)
    width, height = size
    for corner in (
        (0, 0), (width, 0), (0, height), (width, height),
        (0, height * 0.45), (width, height * 0.45),
    ):
        draw.line([corner, (vanishing_x, vanishing_y)], fill=(20, 20, 25), width=5)
    return canvas


def two_tone(junction_ratio=0.62, size=(WIDTH, HEIGHT)):
    """A pale wall over a dark floor, meeting in one hard horizontal edge."""
    width, height = size
    canvas = Image.new("RGB", size, (210, 210, 210))
    ImageDraw.Draw(canvas).rectangle(
        [0, round(height * junction_ratio), width, height], fill=(60, 60, 62)
    )
    return canvas


# ── The vanishing point ────────────────────────────────────────────────────────

def test_the_horizon_is_found_where_the_lines_converge():
    """The measurement Phase 1 stands on."""
    geometry = backdrop_analysis.analyse(room(vanishing_y=400))

    assert geometry.horizon_method == "vanishing_point"
    assert geometry.horizon_y_ratio == pytest.approx(400 / HEIGHT, abs=0.02)
    assert geometry.horizon_confidence > 0.5


@pytest.mark.parametrize("vanishing_y", [250, 400, 550])
def test_the_horizon_follows_the_scene_rather_than_the_frame(vanishing_y):
    """Three rooms photographed from three heights must report three horizons."""
    geometry = backdrop_analysis.analyse(room(vanishing_y=vanishing_y))
    assert geometry.horizon_y_ratio == pytest.approx(vanishing_y / HEIGHT, abs=0.02)


def test_texture_alone_does_not_invent_a_horizon():
    """Random speckle produces thousands of short segments that cross each other
    everywhere.
    """
    noise = np.random.default_rng(0).integers(0, 255, (HEIGHT, WIDTH, 3), dtype=np.uint8)
    geometry = backdrop_analysis.analyse(Image.fromarray(noise, "RGB"))
    assert geometry.horizon_confidence < 0.5


# ── The floor ──────────────────────────────────────────────────────────────────

def test_the_floor_junction_is_found_from_a_tonal_step():
    """The wall-floor junction is where a vehicle could stand furthest back."""
    geometry = backdrop_analysis.analyse(two_tone(junction_ratio=0.62))

    assert geometry.floor_top_y_ratio == pytest.approx(0.62, abs=0.01)
    assert geometry.floor_confidence > 0.5


def test_a_marking_on_one_surface_is_not_a_junction():
    """A painted stripe has a strong gradient on both of its edges and no change of
    surface across it.
    """
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (200, 200, 200))
    ImageDraw.Draw(canvas).rectangle([0, 500, WIDTH, 512], fill=(120, 120, 120))
    geometry = backdrop_analysis.analyse(canvas)

    assert geometry.floor_top_y_ratio != pytest.approx(500 / HEIGHT, abs=0.01)


def test_the_floor_is_never_looked_for_above_the_horizon():
    """A showroom's brightest horizontal edge is often the ceiling cove, which outscores
    the junction.
    """
    canvas = room(vanishing_y=400)
    ImageDraw.Draw(canvas).rectangle([0, 100, WIDTH, 130], fill=(255, 255, 255))
    geometry = backdrop_analysis.analyse(canvas)

    assert geometry.floor_top_y_ratio > geometry.horizon_y_ratio


# ── Falling back ───────────────────────────────────────────────────────────────

def test_a_seamless_backdrop_falls_back_and_says_so():
    """A white cyclorama has no lines in it to converge and no junction to find, which
    is a real backdrop a dealer may well upload.
    """
    geometry = backdrop_analysis.analyse(Image.new("RGB", (WIDTH, HEIGHT), (245, 245, 245)))

    assert geometry.horizon_method == "assumed"
    assert geometry.horizon_confidence == 0.0
    assert geometry.horizon_y_ratio == pytest.approx(backdrop_analysis.ASSUMED_HORIZON_Y_RATIO)
    assert geometry.floor_top_y_ratio == pytest.approx(
        backdrop_analysis.ASSUMED_FLOOR_TOP_Y_RATIO
    )
    assert geometry.floor_confidence == 0.0


def test_the_assumed_floor_is_the_value_that_shipped_before():
    """The fallback has to be today's hard-coded ground line, or a dealer whose backdrop
    the analyser cannot read would see their listings move.
    """
    assert backdrop_analysis.ASSUMED_FLOOR_TOP_Y_RATIO == pytest.approx(
        compositing.DEALER_BACKDROP.ground_y_ratio
    )


def test_a_junction_without_converging_lines_still_gives_a_horizon():
    """A two-tone backdrop has no diagonals, so the horizon comes from the floor."""
    geometry = backdrop_analysis.analyse(two_tone())

    assert geometry.horizon_method == "floor_junction"
    assert 0.0 < geometry.horizon_confidence < geometry.floor_confidence


def test_analysis_never_raises_on_a_degenerate_image():
    """Backdrop upload runs this on whatever a dealer sends. An exception here would
    turn an odd image into a failed upload rather than a low confidence.
    """
    for image in (
        Image.new("RGB", (1, 1), (0, 0, 0)),
        Image.new("RGB", (4, 400), (255, 255, 255)),
        Image.new("L", (200, 200), 128),
    ):
        geometry = backdrop_analysis.analyse(image)
        assert 0.0 <= geometry.horizon_y_ratio <= 1.0
        assert 0.0 <= geometry.floor_top_y_ratio <= 1.0


# ── The camera ─────────────────────────────────────────────────────────────────

def test_a_horizon_above_centre_means_the_camera_was_above():
    """The sign convention has to match elevation.py's, because Phase 1 compares the two
    directly.
    """
    high = backdrop_analysis._camera_elevation_deg(300.0, 28.0, (WIDTH, HEIGHT))
    level = backdrop_analysis._camera_elevation_deg(HEIGHT / 2, 28.0, (WIDTH, HEIGHT))
    low = backdrop_analysis._camera_elevation_deg(600.0, 28.0, (WIDTH, HEIGHT))

    assert high > 0
    assert level == pytest.approx(0.0)
    assert low < 0


def test_no_focal_length_means_no_elevation_rather_than_a_guess():
    """An angle cannot be recovered from a horizon position alone."""
    assert backdrop_analysis._camera_elevation_deg(300.0, None, (WIDTH, HEIGHT)) is None
    assert backdrop_analysis.analyse(room()).camera_elevation_deg is None


def test_a_recorded_focal_length_is_read_and_used(tmp_path):
    """A dealer's phone writes the 35 mm equivalent; a render does not."""
    path = tmp_path / "showroom.jpg"
    exif = Image.Exif()
    exif[backdrop_analysis._EXIF_FOCAL_LENGTH_35MM] = 26
    room(vanishing_y=350).save(path, exif=exif)

    geometry = backdrop_analysis.analyse(Image.open(path))

    assert geometry.focal_length_35mm == pytest.approx(26.0)
    assert geometry.camera_elevation_deg is not None
    assert geometry.camera_elevation_deg > 0, "a horizon above centre is a raised camera"


def test_an_impossible_focal_length_is_refused(tmp_path):
    """One corrupt tag would put the elevation wildly out, silently."""
    path = tmp_path / "corrupt.jpg"
    exif = Image.Exif()
    exif[backdrop_analysis._EXIF_FOCAL_LENGTH_35MM] = 9999
    room().save(path, exif=exif)

    assert backdrop_analysis.analyse(Image.open(path)).focal_length_35mm is None


# ── Against the one scene measured by hand ─────────────────────────────────────

def test_the_measured_studio_floor_agrees_with_the_hand_measurement():
    """Suraj Purella measured the studio platform by hand and its top edge sits at 0.598
    of the canvas, which is also where the back wall meets the floor.
    """
    loaded = compositing.load_studio_backdrop("studio_full")
    if loaded is None:
        pytest.skip("the studio backdrop is not present")
    image, preset = loaded

    geometry = backdrop_analysis.analyse(image)

    assert geometry.floor_top_y_ratio == pytest.approx(preset.platform_box[1], abs=0.02)
    assert geometry.floor_confidence > 0.5


def test_the_studio_horizon_sits_above_where_a_vehicle_stands():
    """A sanity check with real geometry behind it: the eye level of a photograph is
    always above the floor in front of the camera, so a horizon reported below the
    contact line would mean the measurement is inverted.
    """
    loaded = compositing.load_studio_backdrop("studio_full")
    if loaded is None:
        pytest.skip("the studio backdrop is not present")
    image, preset = loaded

    geometry = backdrop_analysis.analyse(image)

    assert geometry.horizon_y_ratio < preset.platform_contact_y_ratio

