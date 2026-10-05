# Tests for the vertical shear platform_placement.fit uses to stand an oblique
# vehicle's tyres on the curve of the turntable.
#
# platform_placement.py imports only numpy and PIL, so these run anywhere:
#
#     pytest tests/test_platform_shear.py -v
#
# The defect: the shear moves every column of the car up or down by
# slope * (x - reference) and was drawn onto a canvas exactly the size of the
# unsheared car, so whatever it moved past an edge was cut off — the roof when
# the far wheel is on the left and the slope is negative, the lower body when
# it is on the right and the slope is positive. The only headroom was the two
# pixels trim_transparent leaves round a cutout.
#
# A vertical shear slides each column of pixels up or down whole, without
# adding or removing any, so every column of the car that comes out has to hold
# as much of the car as the same column did going in. That is measured per
# column rather than over the whole car on purpose: fit() may redraw the car a
# few per cent smaller, and rebuilding the unsheared car at that size from its
# width can land a row away from the one fit() drew, which alone moves the
# whole-car count by nearly one per cent. A column is off by a pixel for that;
# a column that lost its roof is off by dozens.

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps

import compositing
import platform_placement

BOX = compositing.STUDIO_FULL.platform_box
SIZES = [(1280, 960), (640, 480)]


def vehicle(w, h, oblique=False):
    """The synthetic car tests/test_platform_placement.py places.

    `oblique` lifts the right-hand wheel by 18% of the height, the far wheel of
    a quarter view sitting higher than the turntable's curve predicts, which is
    what the shear is there to correct.
    """
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((w * .03, h * .28, w * .97, h * .84), radius=12, fill=(145, 30, 35, 255))
    draw.polygon(
        [(w * .2, h * .3), (w * .32, h * .04), (w * .72, h * .04), (w * .88, h * .3)],
        fill=(65, 85, 92, 255),
    )
    for x, dy in ((w * .21, 0), (w * .79, -h * .18 if oblique else 0)):
        draw.ellipse((x - w * .065, h * .66 + dy, x + w * .065, h * .98 + dy), fill=(18, 18, 18, 255))
    return image


def quarter_view(far_wheel):
    """An oblique cutout, trimmed the way compose() hands one over.

    With the raised wheel on the right the shear's slope is positive and it
    pushes the right-hand end down; mirrored, the slope is negative and it
    pushes the right-hand end, roof and all, up.
    """
    cutout = vehicle(650, 420, oblique=True)
    if far_wheel == "left":
        cutout = ImageOps.mirror(cutout)
    return compositing.trim_transparent(cutout)


def solid(image):
    return np.asarray(image.getchannel("A")) >= 128


def solid_height(image):
    rows = np.flatnonzero(solid(image).any(axis=1))
    return int(rows[-1] - rows[0] + 1)


def straight(cutout, placed):
    """The cutout at the size fit() drew it, before any shear.

    The width comes from the placed car because a vertical shear never changes
    it, whatever else fit() did to the size.
    """
    height = round(cutout.height * placed.width / cutout.width)
    return cutout.resize((placed.width, height), Image.Resampling.LANCZOS)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("far_wheel", ["right", "left"], ids=["slope-down", "slope-up"])
def test_the_shear_keeps_every_part_of_the_car(far_wheel, size):
    """
    The defect this exists to catch: 1.0-1.3% of this car's silhouette went
    missing off the bottom with the slope one way, and 3.4-3.7% of it — the
    roof over the raised end — off the top with the slope the other way.
    """
    cutout = quarter_view(far_wheel)
    placed, _, _, supports = platform_placement.fit(cutout, BOX, size)
    before = straight(cutout, placed)

    # The shear has to have run for this to test anything: it is what brings
    # the two tyres level with the curve, so their relative height moves.
    level = platform_placement.contacts(before)
    moved = (supports[-1][1] - supports[0][1]) - (level[-1][1] - level[0][1])
    assert abs(moved) > 10, "the shear did not engage, so nothing here was sheared"

    lost = solid(before).sum(axis=0) - solid(placed).sum(axis=0)
    worst = int(np.argmax(lost))
    assert lost.max() <= 3, (
        f"column {worst} of {placed.width} lost {lost.max()} of its "
        f"{solid(before)[:, worst].sum()} pixels of car"
    )


@pytest.mark.parametrize("size", SIZES)
def test_one_visible_height_whichever_way_the_car_is_turned(size):
    """
    Cutting the roof off made the car shorter than itself: a quarter view with
    its far wheel on the left came out 245 pixels tall against 265 for the same
    shapes stood on the platform unsheared, 8% short on a gallery held to 3%.
    Keeping the roof is not enough by itself either — a shear moves the ends of
    the car up and down by the slope times their distance from the pivot, so
    the silhouette it draws is taller than the one it was given, by 4% here,
    and the size a listing is held to is the one that is drawn. So a sheared
    car has to come out at the height the listing asked for, not at the height
    the shear leaves it.
    """
    shapes = [
        vehicle(400, 380),
        vehicle(1000, 350),
        vehicle(250, 550),
        quarter_view("right"),
        quarter_view("left"),
    ]
    heights = [solid_height(platform_placement.fit(shape, BOX, size)[0]) for shape in shapes]

    assert max(heights) / min(heights) < 1.03, heights


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("far_wheel", ["right", "left"], ids=["slope-down", "slope-up"])
def test_a_sheared_car_still_stands_on_the_platform(far_wheel, size):
    """
    The guard on the bookkeeping. Keeping the whole car means drawing it on a
    taller canvas, and the contacts and the paste position then have to be
    measured on that canvas, or every tyre lands off the turntable by however
    much was added.
    """
    placed, x, y, supports = platform_placement.fit(quarter_view(far_wheel), BOX, size)
    alpha = solid(placed)
    top_surface = compositing._platform_mask(compositing.STUDIO_FULL, size)

    assert len(supports) == 2
    for px, py in supports:
        # Each contact is the bottom of the car in its own column...
        assert alpha[py, px] and not alpha[py + 1:, px].any()
        # ...and it lands on the measured top of the turntable.
        assert top_surface.getpixel((x + px, y + py)) == 255
