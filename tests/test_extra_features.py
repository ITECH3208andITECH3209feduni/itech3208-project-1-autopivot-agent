"""Features ported from the alternate branch: dual-pass plate search, a lasting JWT
secret, the compositor revision, placement warnings, the measured platform mask,
tyre-axis levelling and shared-height sequences.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compositing  # noqa: E402
from scripts import ensure_env  # noqa: E402
from test_compositing import CAR_ASPECTS, silhouette  # noqa: E402


# ── .env / JWT secret ─────────────────────────────────────────────────────────

def test_ensure_env_adds_a_secret_once_and_keeps_everything_else(tmp_path):
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=abc\r\nDATABASE_URL=sqlite:///x.db\r\n", encoding="utf-8")

    assert ensure_env.ensure_env(env, tmp_path / "missing.example") == "added"
    text = env.read_text(encoding="utf-8")
    assert "HF_TOKEN=abc" in text and "DATABASE_URL=sqlite:///x.db" in text
    secret = [line for line in text.splitlines() if line.startswith("JWT_SECRET=")][0]
    assert len(secret.split("=", 1)[1]) >= 32
    assert "\r\n" in env.read_bytes().decode()  # Windows line endings kept

    assert ensure_env.ensure_env(env, tmp_path / "missing.example") == "ok"
    assert env.read_text(encoding="utf-8") == text


def test_ensure_env_fills_an_empty_placeholder_and_creates_from_example(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("JWT_SECRET=\nPLATE_TREATMENT=blur\n", encoding="utf-8")
    env = tmp_path / ".env"

    assert ensure_env.ensure_env(env, example) == "created"
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines.count("PLATE_TREATMENT=blur") == 1
    (secret_line,) = [line for line in lines if line.startswith("JWT_SECRET=")]
    assert len(secret_line) > len("JWT_SECRET=") + 32


# ── Plate search: 1x + 2x, merged ─────────────────────────────────────────────

def _box(x1, y1, x2, y2, score):
    return {"score": score, "label": "plate",
            "box": {"xmin": x1, "ymin": y1, "xmax": x2, "ymax": y2}}


def test_plate_search_merges_the_enlarged_pass(monkeypatch):
    backend = pytest.importorskip("autopivot_backend")
    calls = []

    def fake_detector(image):
        calls.append(image.size)
        if len(calls) == 1:  # 1x: the plate is just under the threshold
            return [_box(100, 200, 160, 220, backend.PLATE_CONFIDENCE - 0.05)]
        return [_box(200, 400, 320, 440, 0.8)]

    class FakeRegistry:
        plate_detector = staticmethod(fake_detector)

    monkeypatch.setattr(backend, "registry", FakeRegistry())
    monkeypatch.setattr(backend, "PLATE_UPSCALE", 2.0)
    found = backend._detect_plates(Image.new("RGBA", (400, 300)))

    assert calls == [(400, 300), (800, 600)]
    assert len(found) == 1
    assert found[0]["box"] == {"xmin": 100, "ymin": 200, "xmax": 160, "ymax": 220}


def test_plate_search_does_not_double_count_one_plate(monkeypatch):
    backend = pytest.importorskip("autopivot_backend")
    answers = iter([[_box(100, 200, 160, 220, 0.9)], [_box(202, 398, 322, 442, 0.7)]])
    class FakeRegistry:
        plate_detector = staticmethod(lambda image: next(answers))

    monkeypatch.setattr(backend, "registry", FakeRegistry())
    monkeypatch.setattr(backend, "PLATE_UPSCALE", 2.0)
    found = backend._detect_plates(Image.new("RGBA", (400, 300)))
    assert len(found) == 1 and found[0]["score"] == 0.9


# ── Compositor ────────────────────────────────────────────────────────────────

def _studio():
    backdrop, preset = compositing.load_studio_backdrop("studio_full")
    assert backdrop is not None
    return backdrop, preset


def test_every_result_records_the_compositor_version_and_engine():
    backdrop, preset = _studio()
    _, meta = compositing.compose(silhouette(2.4), backdrop, preset, angle="front_quarter")
    assert meta["compositor_revision"] == compositing.COMPOSITOR_REVISION
    assert meta["placement_engine"] == "platform"
    assert isinstance(meta["placement_warnings"], list)
    assert meta["tyre_contact_details"], "the tyres should have been found"


def test_tyres_stand_on_the_measured_platform_mask():
    import dataclasses
    backdrop, preset = _studio()
    preset = dataclasses.replace(preset, zoom=1.0)  # canvas pixels = mask pixels
    for angle, aspect in CAR_ASPECTS.items():
        _, meta = compositing.compose(silhouette(aspect), backdrop, preset, angle=angle)
        size = (meta["output_size"]["width"], meta["output_size"]["height"])
        mask = compositing._platform_mask(preset, size)
        real = [c for c in meta["tyre_contact_details"] if c["method"] != "virtual_axle_contact"]
        assert real, f"{angle}: no tyres found"
        for contact in real:
            assert mask.getpixel((contact["x"], contact["y"])) >= 250, (
                f"{angle}: tyre at {contact} is off the platform")


def test_measured_mask_is_used_for_the_studio():
    mask = compositing._platform_mask(compositing.STUDIO_FULL, (1448, 1086))
    bbox = mask.point(lambda v: 255 if v >= 250 else 0).getbbox()
    assert bbox is not None
    assert abs(bbox[1] - 657) <= 3 and abs(bbox[3] - 881) <= 3


def test_front_view_is_never_rolled_but_a_tilted_side_view_is_levelled():
    front = silhouette(1.2)
    _, rotation = compositing._level_with_tyres(front, "front", 0.9)
    assert rotation is None

    side = silhouette(3.13).rotate(5, expand=True, resample=Image.Resampling.BICUBIC)
    side = compositing.trim_transparent(side)
    levelled, rotation = compositing._level_with_tyres(side, "side", 0.9)
    if rotation is not None:
        assert 2.0 <= abs(rotation) <= 8.0


def test_a_sequence_draws_every_view_at_one_height():
    backdrop, preset = _studio()
    angles = list(CAR_ASPECTS)
    cutouts = [silhouette(CAR_ASPECTS[a]) for a in angles]
    results = compositing.compose_sequence(cutouts, backdrop, preset, angles=angles)

    heights = [meta["vehicle_height_px"] for _, meta in results]
    assert max(heights) - min(heights) <= 3, heights
    assert all(meta["sequence_count"] == len(angles) for _, meta in results)


def test_sequence_rejects_mismatched_angles():
    backdrop, preset = _studio()
    with pytest.raises(ValueError):
        compositing.compose_sequence([silhouette(2.0)], backdrop, preset, angles=["side", "front"])


def test_classic_engine_is_still_available(monkeypatch):
    monkeypatch.setattr(compositing, "PLACEMENT_ENGINE", "classic")
    backdrop, preset = _studio()
    _, meta = compositing.compose(silhouette(2.4), backdrop, preset, angle="front_quarter")
    assert meta["placement_engine"] == "classic"


# ── Fixes from reviewing the 2026-10-08 results ───────────────────────────────

def test_a_coloured_fill_is_never_painted_as_a_tyre():
    """The red Tiggo got a pink disc on the floor: a circle fitted beside the wheel was
    'filled' with paint colour. Only dark grey rubber may be used.
    """
    car = Image.new("RGBA", (600, 260), (0, 0, 0, 0))
    draw = ImageDraw.Draw(car)
    draw.rectangle((20, 40, 580, 200), fill=(200, 30, 30, 255))      # red body
    draw.ellipse((80, 140, 200, 260), fill=(200, 30, 30, 255))       # red "wheel"
    draw.ellipse((400, 140, 520, 260), fill=(200, 30, 30, 255))
    car = car.crop((0, 0, 600, 230))                                 # shave the bottoms
    patched = compositing._patch_wheel_gaps(car, "rear_quarter")
    added = (patched.getchannel("A").point(lambda v: 255 if v > 128 else 0).histogram()[255]
             - car.getchannel("A").point(lambda v: 255 if v > 128 else 0).histogram()[255])
    assert added <= 50, "a red fill was painted where a tyre was missing"


def test_a_roof_aerial_touching_the_top_is_not_a_cut_off_car():
    backend = pytest.importorskip("autopivot_backend")
    car = Image.new("RGBA", (800, 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(car)
    draw.rectangle((100, 60, 700, 480), fill=(120, 120, 120, 255))   # body, clear of top
    draw.rectangle((395, 0, 405, 60), fill=(20, 20, 20, 255))        # shark-fin aerial
    assert backend._only_a_thin_part_touches_the_top(car, 600)

    roof_cut = Image.new("RGBA", (800, 500), (0, 0, 0, 0))
    ImageDraw.Draw(roof_cut).rectangle((100, 0, 700, 480), fill=(120, 120, 120, 255))
    assert not backend._only_a_thin_part_touches_the_top(roof_cut, 600)


def test_frame_edges_are_reported_individually():
    backend = pytest.importorskip("autopivot_backend")
    box = {"xmin": 50, "ymin": 0, "xmax": 900, "ymax": 700}
    assert backend._frame_edges_touched(box, (1000, 800)) == {"top"}
    box = {"xmin": 0, "ymin": 0, "xmax": 900, "ymax": 700}
    assert backend._frame_edges_touched(box, (1000, 800)) == {"left", "top"}


# ── Studio relight, other-car removal, no quarter warp ────────────────────────

def _painted_car(colour=(190, 30, 35)):
    """A drawn side-on car: paint body, dark glass band, black tyres."""
    car = Image.new("RGBA", (900, 330), (0, 0, 0, 0))
    d = ImageDraw.Draw(car)
    d.rounded_rectangle((20, 120, 880, 270), radius=30, fill=colour + (255,))
    d.polygon([(200, 125), (300, 30), (640, 30), (760, 125)], fill=colour + (255,))
    d.polygon([(230, 118), (315, 45), (620, 45), (720, 118)], fill=(40, 42, 45, 255))  # glass
    for cx in (190, 710):
        d.ellipse((cx - 62, 210, cx + 62, 330), fill=(20, 20, 20, 255))
        d.ellipse((cx - 35, 237, cx + 35, 303), fill=(185, 185, 185, 255))
    return car


def test_relight_keeps_the_paint_colour_and_the_silhouette():
    car = _painted_car()
    lit = compositing.studio_relight(car)
    assert lit.size == car.size
    assert (np.array(lit)[:, :, 3] == np.array(car)[:, :, 3]).all()
    import cv2
    before = cv2.cvtColor(np.array(car.convert("RGB")), cv2.COLOR_RGB2LAB)[150:250, 400:500]
    after = cv2.cvtColor(np.array(lit.convert("RGB")), cv2.COLOR_RGB2LAB)[150:250, 400:500]
    hue_before = np.degrees(np.arctan2(before[..., 2].astype(float) - 128, before[..., 1].astype(float) - 128)).mean()
    hue_after = np.degrees(np.arctan2(after[..., 2].astype(float) - 128, after[..., 1].astype(float) - 128)).mean()
    assert abs(hue_before - hue_after) < 6, "the car changed colour"


def test_relight_keeps_the_original_brightness():
    """The studio look may lift the car slightly but must not wash it out or darken it."""
    for colour in ((150, 152, 155), (40, 42, 46), (190, 30, 35)):  # silver, dark, red
        car = _painted_car(colour)
        lit = np.array(compositing.studio_relight(car).convert("L"), dtype=float)
        base = np.array(car.convert("L"), dtype=float)
        body = np.array(car)[:, :, 3] > 0
        change = np.median(lit[body]) - np.median(base[body])
        assert -4 < change < 18, colour


def test_relight_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(compositing, "STUDIO_RELIGHT", False)
    backdrop, preset = _studio()
    _, meta = compositing.compose(_painted_car(), backdrop, preset, angle="side")
    assert meta["studio_graded"] is True


def test_quarter_views_are_never_bent_by_the_platform_engine():
    backdrop, preset = _studio()
    _, meta = compositing.compose(silhouette(2.4), backdrop, preset,
                                  angle="rear_quarter", angle_confidence=0.95)
    assert meta["quarter_ground_correction_px"] is None


def test_wheel_search_is_fast_on_a_big_busy_image():
    import time
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (1400, 2600, 3), dtype=np.uint8)
    car = Image.fromarray(noise).convert("RGBA")
    start = time.time()
    compositing._wheel_contacts(car)
    assert time.time() - start < 8.0


def test_pieces_of_another_car_are_removed():
    import vehicle_isolation as vi
    cutout = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(cutout)
    d.rectangle((20, 80, 380, 190), fill=(90, 90, 95, 255))     # our car
    d.rectangle((300, 40, 390, 80), fill=(240, 240, 240, 255))  # car behind, over the bonnet
    ours = np.zeros((200, 400), bool); ours[80:191, 20:381] = True
    theirs = np.zeros((200, 400), bool); theirs[30:85, 290:400] = True
    cleaned, removed = vi.remove_other_vehicles(cutout, [ours, theirs], (20, 80, 380, 190))
    a = np.array(cleaned)[:, :, 3]
    assert removed > 0
    assert a[45:75, 310:385].max() == 0, "the other car is still there"
    assert a[100:180, 40:360].min() == 255, "our car was damaged"


def test_other_car_removal_does_nothing_with_one_car():
    import vehicle_isolation as vi
    cutout = Image.new("RGBA", (100, 50), (10, 10, 10, 255))
    out, removed = vi.remove_other_vehicles(cutout, [np.ones((50, 100), bool)], (0, 0, 100, 50))
    assert removed == 0 and out is cutout


def test_badge_lettering_is_not_blurred_as_a_second_plate():
    backend = pytest.importorskip("autopivot_backend")
    plate = _box(100, 300, 200, 340, 0.85)
    badge = _box(110, 200, 230, 225, 0.31)   # "VENUE" on the tailgate
    sticker = _box(0, 0, 10, 10, 1.0)
    kept = backend._one_plate_per_end([badge, plate, sticker])
    assert plate in kept and sticker in kept and badge not in kept
    strong_second = _box(400, 300, 500, 340, 0.9)
    assert strong_second in backend._one_plate_per_end([plate, strong_second])


def test_no_fake_tyre_fill_by_default():
    """The tyre-gap fill drew fake discs on real photos; it is off unless asked."""
    assert compositing.WHEEL_GAP_PATCH is False


def test_our_own_roof_is_never_removed_as_another_car():
    """A Nissan Juke's roof and windows came back from the outline model as a second
    car, and were cut off.
    """
    import vehicle_isolation as vi
    cutout = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle((20, 20, 380, 190), fill=(30, 60, 200, 255))
    body = np.zeros((200, 400), bool); body[90:191, 20:381] = True
    roof = np.zeros((200, 400), bool); roof[20:95, 60:340] = True   # 78% of the width
    cleaned, removed = vi.remove_other_vehicles(cutout, [body, roof], (20, 20, 380, 190))
    assert removed == 0
    assert np.array(cleaned)[30:80, 80:320, 3].min() == 255

