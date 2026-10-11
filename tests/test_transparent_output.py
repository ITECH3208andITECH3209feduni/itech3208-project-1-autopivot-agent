# With no backdrop, the finished image is the cutout back in its place on a
# transparent canvas the size of the photograph — the cutout itself, not a
# darker and thinner copy of it.
#
# _place_on_backdrop pasted the cutout through its own alpha as a mask. A masked
# paste blends every band with what is underneath, alpha included, so over a
# canvas of (0, 0, 0, 0) the colour came out multiplied by a/255 and the alpha
# by a/255 a second time: an antialiased edge pixel (255, 255, 255, 128) became
# (128, 128, 128, 64). Everything BiRefNet's mask leaves between 0 and 255 is the
# silhouette's soft edge, so the whole outline went dark and half as opaque — a
# grey fringe on whatever page the PNG is placed on. compositing.compose avoids
# the same trap ("using alpha as a paste mask would apply it twice").
#
# These import autopivot_backend, which needs the ML environment
# (requirements-ml.txt). No model is involved.
#
#     pytest tests/test_transparent_output.py -v

import pytest
from PIL import Image

import autopivot_backend as backend


PHOTO_SIZE = (60, 40)
AT = (10, 5)  # where the crop sat in the photograph


def placed(pixels):
    """Put a one-row cutout back at AT with no backdrop and read it back."""
    cutout = Image.new("RGBA", (len(pixels), 1))
    for x, pixel in enumerate(pixels):
        cutout.putpixel((x, 0), pixel)
    x1, y1 = AT
    final, _ = backend._place_on_backdrop(
        cutout, None, PHOTO_SIZE, (x1, y1, x1 + len(pixels), y1 + 1)
    )
    return final, [final.getpixel((x1 + x, y1)) for x in range(len(pixels))]


@pytest.mark.parametrize("pixel", [
    (255, 255, 255, 128),  # the antialiased edge in the report
    (200, 100, 50, 64),
    (80, 160, 240, 1),
    (10, 20, 30, 255),     # the body of the vehicle
])
def test_the_cutout_keeps_its_own_alpha_and_colour(pixel):
    _, [out] = placed([pixel])
    assert out == pixel


def test_the_canvas_is_the_photograph_and_transparent_around_the_vehicle():
    final, _ = placed([(10, 20, 30, 255)])

    assert (final.mode, final.size) == ("RGBA", PHOTO_SIZE)
    assert final.getpixel((0, 0)) == (0, 0, 0, 0)
    assert final.getpixel((PHOTO_SIZE[0] - 1, PHOTO_SIZE[1] - 1)) == (0, 0, 0, 0)


def test_what_the_background_removal_took_out_does_not_ride_along_in_the_colour():
    """
    BiRefNet's cutout is the photograph with a mask on it: every background
    pixel keeps its colour at alpha 0. A transparent PNG that still carries them
    is the whole scene — passers-by, the car parked behind with its plate — one
    'remove alpha' away in any image editor. So the fix cannot be a plain paste
    without the mask, which copies them through.
    """
    _, [out] = placed([(99, 99, 99, 0)])
    assert out == (0, 0, 0, 0)
