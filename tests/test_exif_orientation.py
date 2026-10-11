# A phone photograph is stored the way the sensor saw it, with a note saying
# which way up it goes.
#
# The Flutter app's capture screen is locked to portrait, and every shot it
# takes is 1280x720 pixels carrying EXIF Orientation 6 — a quarter turn
# clockwise to view. Browsers and Flutter both read that note, so the dealer
# sees an upright car. The pipeline never did: the classifier, the vehicle
# detector, BiRefNet and the compositor were all handed the stored pixels lying
# on their side, and a backdrop was measured the same way, with its floor looked
# for along the wrong axis.
#
# These build such photographs synthetically and check that everything which
# decodes an image — to process it, to measure it, or to record its size — sees
# it the way the dealer does, while the file on disk stays byte for byte what
# was uploaded.
#
# The pipeline test imports autopivot_backend, which needs the ML environment,
# and is skipped without it. The model-backed steps are replaced by recorders,
# so no model is loaded. Everything else here runs anywhere.
#
#     pytest tests/test_exif_orientation.py -v

import io

import pytest
from PIL import Image, ImageDraw

import backdrop_analysis
from api import routes_backdrops, storage


ORIENTATION_TAG = 0x0112
FOCAL_LENGTH_35MM_TAG = 0xA405  # FocalLengthIn35mmFilm

# How a camera stores an upright picture under each orientation, which is the
# inverse of what the tag tells a viewer to do. Taken from the definitions: for
# 6, "the 0th row is the visual right-hand side and the 0th column is the visual
# top", so the picture is stored turned a quarter anticlockwise and shown after
# a quarter turn clockwise. PIL's ROTATE_90 is anticlockwise.
STORED_FROM_UPRIGHT = {
    1: None,
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_90,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_270,
}

# None is a photograph with no EXIF at all, which must be left exactly as it is.
EVERY_ORIENTATION = [None, *STORED_FROM_UPRIGHT]

# The three a camera writes without mirroring anything, plus the untagged case.
CAMERA_ORIENTATIONS = [None, 3, 6, 8]

RED, GREEN, BLUE, GREY = (220, 30, 30), (30, 200, 30), (30, 30, 220), (128, 128, 128)

UPRIGHT_CORNERS = {
    "top left": "red",
    "top right": "green",
    "bottom left": "blue",
    "bottom right": "grey",
}


# ── Building photographs ───────────────────────────────────────────────────────

def as_camera_stores_it(upright, orientation, *, focal_length_35mm=None) -> bytes:
    """
    The JPEG a camera would write for this picture: its pixels turned the way
    the sensor saw them, and a tag saying how to turn them back.
    """
    exif = Image.Exif()
    stored = upright
    if orientation is not None:
        exif[ORIENTATION_TAG] = orientation
        if STORED_FROM_UPRIGHT[orientation] is not None:
            stored = upright.transpose(STORED_FROM_UPRIGHT[orientation])
    if focal_length_35mm is not None:
        # Placed where tests/test_backdrop_analysis.py places it, which is
        # where the analyser reads it from.
        exif[FOCAL_LENGTH_35MM_TAG] = focal_length_35mm

    buffer = io.BytesIO()
    extra = {"exif": exif} if len(exif) else {}
    stored.save(buffer, format="JPEG", quality=95, **extra)
    return buffer.getvalue()


def marked_photo(size=(180, 320)):
    """
    An upright picture whose corners can all be told apart, so any turn or
    mirror of it shows. Portrait by default, the way a phone held upright
    takes one.
    """
    width, height = size
    image = Image.new("RGB", size, GREY)
    draw = ImageDraw.Draw(image)
    block = min(width, height) // 3
    draw.rectangle([0, 0, block, block], fill=RED)
    draw.rectangle([width - 1 - block, 0, width - 1, block], fill=GREEN)
    draw.rectangle([0, height - 1 - block, block, height - 1], fill=BLUE)
    return image


def corners(image) -> dict[str, str]:
    """The colour of each corner of a picture, named as a viewer would name it."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    inset = min(width, height) // 10
    samples = {
        "top left": (inset, inset),
        "top right": (width - 1 - inset, inset),
        "bottom left": (inset, height - 1 - inset),
        "bottom right": (width - 1 - inset, height - 1 - inset),
    }
    return {corner: _nearest_colour(rgb.getpixel(xy)) for corner, xy in samples.items()}


def _nearest_colour(pixel) -> str:
    named = {"red": RED, "green": GREEN, "blue": BLUE, "grey": GREY}
    return min(
        named, key=lambda name: sum((a - b) ** 2 for a, b in zip(pixel, named[name]))
    )


def two_tone(junction_ratio=0.62, size=(1200, 900)):
    """A pale wall over a dark floor, meeting in one hard horizontal edge."""
    width, height = size
    canvas = Image.new("RGB", size, (210, 210, 210))
    ImageDraw.Draw(canvas).rectangle(
        [0, round(height * junction_ratio), width, height], fill=(60, 60, 62)
    )
    return canvas


def room(vanishing_y=400, size=(1200, 900)):
    """A drawn room whose lines converge on a point at a known height."""
    canvas = Image.new("RGB", size, (200, 200, 205))
    draw = ImageDraw.Draw(canvas)
    width, height = size
    for corner in (
        (0, 0), (width, 0), (0, height), (width, height),
        (0, height * 0.45), (width, height * 0.45),
    ):
        draw.line([corner, (width / 2, vanishing_y)], fill=(20, 20, 25), width=5)
    return canvas


def opened(content: bytes):
    return Image.open(io.BytesIO(content))


# ── The pipeline ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("orientation", EVERY_ORIENTATION)
def test_every_step_of_the_pipeline_sees_the_photograph_as_the_dealer_does(
    orientation, monkeypatch
):
    """
    The defect itself. A photograph shown upright to the dealer reached the
    classifier, the detector and BiRefNet on its side, and the compositor then
    stood a sideways car on a sideways backdrop — or the classifier left the
    photograph out altogether, because a car on its side does not look like an
    exterior shot.
    """
    backend = pytest.importorskip("autopivot_backend")
    seen = {}

    def classify(image):
        seen["classifier"] = image.copy()
        return None  # as when CLIP cannot load: the pipeline carries on without it

    def detect_vehicle(image, conf=0.35):
        seen["vehicle detector"] = image.copy()
        width, height = image.size
        return {
            "class": "car",
            "score": 0.9,
            "box": {"xmin": 0, "ymin": 0, "xmax": width, "ymax": height},
            "area": float(width * height),
        }

    def remove_background(crop):
        seen["background removal"] = crop.copy()
        return crop.convert("RGBA"), "recorder"

    def place_on_backdrop(cutout, background, original_size, coords, **_):
        seen["backdrop"] = background.copy()
        seen["canvas size"] = original_size
        return cutout, {}

    monkeypatch.setattr(backend, "_classify", classify)
    monkeypatch.setattr(backend, "_detect_vehicle", detect_vehicle)
    monkeypatch.setattr(backend, "_remove_background", remove_background)
    monkeypatch.setattr(backend, "_detect_plates", lambda crop: [])
    monkeypatch.setattr(backend, "_estimate_elevation", lambda cutout, angle: None)
    monkeypatch.setattr(backend, "_place_on_backdrop", place_on_backdrop)

    photo = as_camera_stores_it(marked_photo((180, 320)), orientation)
    backdrop = as_camera_stores_it(marked_photo((320, 180)), orientation)

    outcome = backend.PipelineProcessor().process(photo, backdrop)

    assert outcome.vehicle_detected
    for step in ("classifier", "vehicle detector", "background removal"):
        assert seen[step].size == (180, 320), step
        assert corners(seen[step]) == UPRIGHT_CORNERS, step
    assert seen["canvas size"] == (180, 320)
    assert seen["backdrop"].size == (320, 180)
    assert corners(seen["backdrop"]) == UPRIGHT_CORNERS


# ── Storage ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("orientation", EVERY_ORIENTATION)
def test_storage_records_the_size_the_photograph_is_seen_at(orientation):
    """
    The recorded width and height describe the picture a viewer sees, which is
    the same one the pipeline now processes. The raw pixel grid of a portrait
    phone photograph is landscape, and recording that says the opposite of
    what every client displays.
    """
    content = as_camera_stores_it(marked_photo((180, 320)), orientation)

    assert storage.inspect_image(content) == ("image/jpeg", 180, 320)


def test_an_upload_is_kept_exactly_as_sent_and_recorded_at_its_upright_size(
    tmp_path, monkeypatch
):
    """
    Turning the photograph upright happens when it is decoded, never by
    rewriting the upload. Files are addressed by the hash of their bytes, and
    every browser and Flutter already honour the tag, so re-encoding would only
    lose quality, discard the camera's own metadata and move the file.
    """
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path.resolve())
    content = as_camera_stores_it(marked_photo((180, 320)), 6)

    stored = storage.save_image(1, "original", content)

    assert (stored.width, stored.height) == (180, 320)
    assert storage.resolve(stored.storage_path).read_bytes() == content


# ── Measuring a backdrop ───────────────────────────────────────────────────────

@pytest.mark.parametrize("orientation", CAMERA_ORIENTATIONS)
def test_a_backdrop_floor_is_found_where_the_dealer_sees_it(orientation):
    """
    Measured on the stored pixels, the floor of a showroom photographed in
    portrait is a vertical edge, which the analyser does not look for, and the
    vehicle is then stood on the assumed line rather than on the floor.
    """
    content = as_camera_stores_it(two_tone(junction_ratio=0.62), orientation)

    geometry = backdrop_analysis.analyse(opened(content))

    assert geometry.floor_top_y_ratio == pytest.approx(0.62, abs=0.01)
    assert geometry.floor_confidence > 0.5


@pytest.mark.parametrize("orientation", CAMERA_ORIENTATIONS)
def test_a_backdrop_horizon_is_found_where_the_dealer_sees_it(orientation):
    content = as_camera_stores_it(room(vanishing_y=400), orientation)

    geometry = backdrop_analysis.analyse(opened(content))

    assert geometry.horizon_method == "vanishing_point"
    assert geometry.horizon_y_ratio == pytest.approx(400 / 900, abs=0.02)


@pytest.mark.parametrize("orientation", [3, 6, 8])
def test_turning_a_backdrop_upright_keeps_what_the_camera_recorded(orientation):
    """
    The orientation lives in the same EXIF block as the focal length, which is
    what turns a horizon position into a camera elevation. Turning the picture
    upright must not cost the one number that makes the elevation a
    measurement, and the elevation must then be the one the upright scene gives.
    """
    scene = room(vanishing_y=350)
    reference = backdrop_analysis.analyse(
        opened(as_camera_stores_it(scene, None, focal_length_35mm=26))
    )

    geometry = backdrop_analysis.analyse(
        opened(as_camera_stores_it(scene, orientation, focal_length_35mm=26))
    )

    assert geometry.focal_length_35mm == pytest.approx(26.0)
    assert reference.camera_elevation_deg > 0, "a horizon above centre is a raised camera"
    assert geometry.camera_elevation_deg == pytest.approx(
        reference.camera_elevation_deg, abs=0.5
    )


def test_a_backdrop_uploaded_from_a_phone_is_measured_upright():
    """The upload route's own entry point, which is where measurements are stored."""
    geometry = routes_backdrops._measure(
        as_camera_stores_it(two_tone(junction_ratio=0.62), 6)
    )

    assert geometry is not None
    assert geometry.floor_top_y_ratio == pytest.approx(0.62, abs=0.01)
