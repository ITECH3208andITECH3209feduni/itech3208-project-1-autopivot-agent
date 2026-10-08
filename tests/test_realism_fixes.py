"""Contact shadow, the wheel patch and thin-pole removal (Oct 2026 realism pass)."""

import numpy as np
from PIL import Image, ImageDraw

import compositing


def _car(width=900, height=300):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 40, width - 20, height - 70), 30, fill=(30, 40, 90, 255))
    for cx in (180, width - 180):
        d.ellipse((cx - 70, height - 140, cx + 70, height), fill=(20, 20, 20, 255))
    return img


def test_the_floor_under_the_car_is_darkened(monkeypatch):
    backdrop, preset = compositing.load_studio_backdrop("studio_full")
    with_shadow, meta = compositing.compose(_car(), backdrop, preset, angle="side")
    monkeypatch.setattr(compositing, "_contact_occlusion", lambda *a, **k: None)
    without, _ = compositing.compose(_car(), backdrop, preset, angle="side")

    ground = meta["contact_y_px"]
    place = meta["vehicle_placement"]
    x0 = place["x"] + place["width"] // 3
    x1 = place["x"] + 2 * place["width"] // 3
    band = (slice(ground + 2, ground + 8), slice(x0, x1))
    dark = np.asarray(with_shadow.convert("L"), dtype=np.float32)[band].mean()
    light = np.asarray(without.convert("L"), dtype=np.float32)[band].mean()
    assert dark < light * 0.8, "the contact shadow should clearly darken the floor"


def test_the_floor_line_follows_a_receding_wheel():
    edges = {x: 100.0 for x in range(0, 50)}
    edges.update({x: 140.0 for x in range(150, 200)})
    edges.update({x: 90.0 for x in range(50, 150)})
    floor = compositing._floor_line(edges)
    assert floor[0] == 100.0 and floor[199] == 140.0
    assert 100.0 < floor[100] < 140.0  # runs tyre to tyre, not flat


def test_no_wheel_patch_on_rear_shots():
    car = _car()
    assert compositing._patch_wheel_gaps(car, "rear") is car
    assert compositing._patch_wheel_gaps(car, "front") is car


def test_a_thin_pole_touching_the_car_is_cut_off():
    mask = Image.new("L", (900, 400), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle((100, 150, 800, 380), fill=255)      # the car
    d.ellipse((60, 160, 120, 200), fill=255)          # a mirror, kept
    d.rectangle((150, 10, 156, 150), fill=255)        # a 7 px pole, removed
    refined = np.asarray(compositing.refine_alpha_mask(mask))
    assert refined[60:120, 150:157].max() == 0
    assert refined[175:185, 70:110].max() > 200
    assert refined[300, 450] > 250


def test_studio_grade_brightens_adds_light_and_keeps_the_paint_colour():
    h, w = 300, 900
    yy, xx = np.mgrid[0:h, 0:w]
    paint = np.zeros((h, w, 3), np.float32); paint[:] = (30, 90, 200)       # blue
    blotch = 30 * np.sin(xx / 35.0) * np.cos(yy / 30.0)                     # tree reflections
    detail = np.zeros((h, w), np.float32); detail[:, ::9] = 50              # thin panel lines
    img = np.clip(paint + blotch[..., None] + detail[..., None], 0, 255).astype(np.uint8)
    car = Image.fromarray(np.dstack([img, np.full((h, w), 255, np.uint8)]), "RGBA")

    graded = np.asarray(compositing.studio_grade(car)).astype(np.float32)[..., :3]
    before = np.asarray(car).astype(np.float32)[..., :3]
    inner = (slice(40, 260), slice(160, 740))

    assert graded[inner].mean() > before[inner].mean() + 3
    shoulder = graded[int(h * 0.30), 300:600].mean() - before[int(h * 0.30), 300:600].mean()
    sill = graded[int(h * 0.85), 300:600].mean() - before[int(h * 0.85), 300:600].mean()
    assert shoulder > sill + 8
    def hue(a):
        import cv2
        return cv2.cvtColor(a.astype(np.uint8)[None], cv2.COLOR_RGB2HSV)[0, :, 0].mean()
    assert abs(hue(graded[inner].reshape(-1, 3)) - hue(before[inner].reshape(-1, 3))) < 4
    assert np.abs(np.diff(graded[150, 200:500, 1])).mean() > 0.8 * np.abs(np.diff(before[150, 200:500, 1])).mean()

