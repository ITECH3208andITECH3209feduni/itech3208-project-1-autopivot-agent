"""Zooming into the studio, and picking a backdrop per shot angle."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
from PIL import Image

import compositing
from api import processing


def car(width=900, height=300):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    arr = np.array(img)
    arr[20:height - 10, 10:width - 10] = (200, 30, 30, 255)
    return Image.fromarray(arr, "RGBA")


def test_zoom_makes_the_car_bigger_and_keeps_the_output_size():
    backdrop, preset = compositing.load_studio_backdrop("studio_full")
    flat, flat_meta = compositing.compose(car(), backdrop, replace(preset, zoom=1.0))
    zoomed, zoomed_meta = compositing.compose(car(), backdrop, replace(preset, zoom=1.25))
    assert zoomed.size == flat.size == preset.output_size
    assert zoomed_meta["vehicle_height_px"] > flat_meta["vehicle_height_px"] * 1.2
    placement = zoomed_meta["vehicle_placement"]
    assert 0 <= placement["x"] and placement["x"] + placement["width"] <= zoomed.width
    assert 0 <= zoomed_meta["contact_y_px"] < zoomed.height


def test_dealer_backdrops_are_never_zoomed():
    scene = Image.new("RGB", (1600, 1200), (120, 110, 100))
    out, meta = compositing.compose(car(), scene, replace(compositing.DEALER_BACKDROP, zoom=1.5))
    assert out.size == (1600, 1200)
    assert "zoom" not in meta


class _Session:
    def __init__(self, backdrops):
        self._backdrops = backdrops

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: self._backdrops)


def _backdrop(id, angles):
    return SimpleNamespace(
        id=id, dealership_id=1, suits_angles=angles, storage_path=f"b{id}.png",
        horizon_y_ratio=None, floor_top_y_ratio=None,
    )


def test_a_backdrop_tagged_for_the_angle_replaces_an_untagged_choice(monkeypatch):
    monkeypatch.setattr(
        processing.storage, "resolve",
        lambda path: SimpleNamespace(read_bytes=lambda: path.encode()),
    )
    chosen, rear = _backdrop(1, []), _backdrop(2, ["rear", "rear_quarter"])
    pick = processing._angle_backdrops(_Session([chosen, rear]), chosen)

    assert pick("rear").backdrop_id == 2
    assert pick("rear").image == b"b2.png"
    assert pick("front") is None          # nothing tagged: keep the run's choice
    assert pick(None) is None             # angle unknown: keep the run's choice


def test_a_chosen_backdrop_already_tagged_for_the_angle_is_kept():
    chosen, other = _backdrop(1, ["side"]), _backdrop(2, ["side"])
    pick = processing._angle_backdrops(_Session([chosen, other]), chosen)
    assert pick("side") is None


def test_no_tagged_backdrops_means_no_selector():
    chosen = _backdrop(1, [])
    assert processing._angle_backdrops(_Session([chosen]), chosen) is None

