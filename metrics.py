"""Numbers for judging whether a realism change actually worked.

REALISM_PLAN.md closes on four measures. One of them — the same vehicle before
and after, put in front of somebody who has not seen the code — is a person's
judgement and stays that way. The other three are numbers, and this is where
they live: how far the vehicle's horizon misses the backdrop's, how much
genuine fractional alpha the cut-out edge carries, and how much the car changes
size across one listing's gallery.

They are here rather than inside the tests that assert them today because a
phase has to be able to report its before and its after. A pytest assertion
says that this build is no worse than the last one; it cannot say by how much
anything improved, it cannot be written onto a job record, and it cannot be
quoted in the report. The size spread is the case in point: the project already
claims 1.000 across angles, and that claim currently exists only as a
comparison buried inside `test_one_car_is_one_size_whatever_way_it_faces`.

Nothing here composites or estimates anything — each function takes what has
already been rendered or measured and reduces it to a single figure. That is
what keeps the module clear of the pipeline: it imports cv2, numpy and PIL and
nothing else, so a phase can be measured on a laptop against a folder of
finished images, with no GPU and no model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

# Where the silhouette is taken to begin, for the purpose of finding its
# boundary. The half-alpha contour is the edge a viewer reads. Taking anything
# above zero instead would put the boundary at the outer end of a soft edge and
# swing the band clear of the very pixels it exists to count, so the softer and
# better resolved the matte, the lower it would score.
EDGE_SOLID_ALPHA = 128

# Half-width of the boundary band, as a fraction of the silhouette's own
# bounding-box diagonal — about four pixels for a car filling a 1280-wide
# composite, and never less than one.
#
# The band has to be derived from something that scales, or the measure ends up
# describing the size of the picture rather than the quality of its edge. A
# band fixed at, say, three pixels contains the whole of a soft edge on a
# 1280-wide composite and only the middle of that same edge re-rendered at
# 4000, so the better-resolved image scores worse. Deriving the band from the
# silhouette rather than from the canvas additionally makes it blind to
# framing: the same car measured on its trimmed cutout and again on the 4:3
# frame it was placed into is the same edge, and a large transparent margin
# must not move the number.
#
# The width itself is a compromise between two failures. Too wide and the
# denominator fills with pixels far enough inside the body that no matting
# model would ever have made them fractional, so every score is dragged towards
# zero and a real improvement barely registers. Too narrow and the band sits
# entirely within the ramp of any soft edge, where a mask that has merely been
# blurred scores as well as one that is genuinely matted.
EDGE_BAND_RATIO = 0.004


@dataclass(frozen=True)
class EdgeQuality:
    """
    How much of a cut-out's boundary is genuinely fractional rather than cut.

    The two counts are kept alongside the ratio because the ratio on its own
    cannot be pooled. Averaging the ratios over a hundred photographs weights a
    wing mirror the same as a whole car, whereas the counts add up across the
    set and are divided once at the end.
    """

    # Pixels in the band whose alpha is strictly between 0 and 255.
    fractional: int
    # Pixels in the boundary band, which is what the count is measured over.
    silhouette: int
    # fractional / silhouette, 0.0 to 1.0. Zero when there is no boundary.
    ratio: float


def _alpha_of(image: Image.Image) -> np.ndarray:
    """
    The alpha to measure, as uint8.

    A single-channel image is taken as the alpha itself, because that is what
    `compositing.refine_alpha_mask` returns — an "L" mask — while the cutout
    the pipeline carries around is RGBA, and both are things somebody will hand
    to this module. Converting an "L" image to RGBA fabricates a fully opaque
    alpha channel, and a mask measured that way scores zero: exactly the answer
    a hopelessly binary matte gives, which makes the mistake invisible.
    """
    bands = image.getbands()
    if "A" in bands:
        return np.array(image.getchannel("A"), dtype=np.uint8)
    if len(bands) == 1:
        return np.array(image.convert("L"), dtype=np.uint8)
    return np.full((image.height, image.width), 255, dtype=np.uint8)


def edge_quality(image: Image.Image) -> EdgeQuality:
    """
    Count the alpha values strictly between 0 and 255 along the silhouette.

    This is the number Phase 3 will be judged on. A mask that has been reduced
    to a yes or a no per pixel carries none of these values at all and scores
    zero; a matting model returns genuine coverage — the fraction of the pixel
    the aerial actually occupies — and scores high.

    Worth stating plainly, because the figure will be quoted: this counts how
    much of the boundary carries fractional alpha, not where that alpha came
    from. Interpolating a mask decided at 1024x1024 up to a photograph three
    times as wide invents fractional values of its own, and they are counted
    here like any other, so the pipeline as it stands does not score zero.
    Phase 3 has to move that baseline rather than create it, and the reason it
    should move is that matting resolves boundary the segmentation never had —
    spokes, aerials, mirror stalks — and along that kind of boundary nearly
    every pixel of the band is fractional.

    The count is taken over a band around the boundary rather than over the
    whole image; see EDGE_BAND_RATIO for how wide that band is and why it is
    derived from the silhouette instead of from the canvas.

    An image with no boundary in it — a finished composite, which is opaque
    everywhere, or an empty cutout — returns zeros rather than raising. That is
    a caller measuring the wrong image, and a zero in a results table is a more
    useful thing to be handed than a traceback halfway through a batch.
    """
    alpha = _alpha_of(image)
    solid = np.where(alpha >= EDGE_SOLID_ALPHA, 255, 0).astype(np.uint8)

    rows, columns = np.nonzero(solid)
    if rows.size == 0:
        return EdgeQuality(0, 0, 0.0)

    diagonal = float(np.hypot(
        columns.max() - columns.min() + 1,
        rows.max() - rows.min() + 1,
    ))
    radius = max(1, round(EDGE_BAND_RATIO * diagonal))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
    )

    # OpenCV pads for erosion with the maximum and for dilation with the
    # minimum, so a vehicle running off the side of the frame is not given a
    # band along the frame edge. That matters: the crop boundary is not a
    # silhouette, no matting model could ever make it fractional, and counting
    # it would penalise every tightly cropped photograph.
    in_band = cv2.subtract(cv2.dilate(solid, kernel), cv2.erode(solid, kernel)) > 0
    silhouette = int(np.count_nonzero(in_band))
    if silhouette == 0:
        return EdgeQuality(0, 0, 0.0)

    fractional = int(np.count_nonzero(in_band & (alpha > 0) & (alpha < 255)))
    return EdgeQuality(fractional, silhouette, fractional / silhouette)


def horizon_offset(
    vehicle_horizon_ratio: float,
    backdrop_horizon_ratio: float,
    canvas_height: int,
) -> float:
    """
    How far the vehicle's horizon misses the backdrop's, in canvas pixels.

    Positive means the vehicle's horizon sits below the backdrop's: the
    photograph was taken from lower than the scene was rendered from, so the
    wall-floor junction behind the car reads as too high. Negative is the
    overhead phone shot dropped into an eye-level room.

    Both ratios are measured down the canvas, 0 at the top edge and 1 at the
    bottom, because that is already how `BackdropPreset` expresses
    `ground_y_ratio` and `platform_contact_y_ratio`; a second convention for
    the same axis in the same project would be a standing invitation to get the
    sign wrong, and the sign is most of what this number is for.

    The answer is in pixels rather than as a ratio so that a studio composite
    on its measured 1280x960 canvas and a dealer's own backdrop at whatever
    size they uploaded can be compared, and so that the offset can be read
    against the vehicle's own rendered height.

    Neither input exists yet, which is why they are arguments rather than
    something this function goes and reads. Once Phase 1 lands,
    `vehicle_horizon_ratio` comes from the camera elevation estimated from the
    source photograph — the wheel-ellipse estimate, with its documented
    fallbacks — projected onto the output canvas; `backdrop_horizon_ratio`
    comes from a new field on `BackdropPreset`, measured per scene alongside
    its platform box, and measured once per camera-height variant.
    """
    return (vehicle_horizon_ratio - backdrop_horizon_ratio) * canvas_height


def size_spread(heights: Sequence[float]) -> float:
    """
    The largest rendered vehicle height in a gallery over the smallest.

    Gallery coherence. 1.0 means every photograph of the listing renders the
    car at one size, which is what the project measures today and what must not
    regress. The arithmetic is deliberately the same as the assertion that
    already guards it in `test_one_car_is_one_size_whatever_way_it_faces` —
    max over min of the rendered heights — because a second coherence number
    defined slightly differently would let the two disagree about a gallery
    neither of them changed, and then neither figure would be believed.

    Feed it `compose()`'s "vehicle_height_px" for every photograph in one
    listing. The worst pair is the point: a mean or a standard deviation hides
    one badly sized photograph among a dozen good ones, and the odd one out is
    exactly what a dealer scrolling the gallery notices.

    A height of zero means nothing was rendered at all. That is a failed job
    rather than an incoherent gallery, so it raises instead of returning an
    infinity that would go into a report looking like a measurement.
    """
    if not heights:
        raise ValueError("size spread needs at least one rendered height")
    smallest, largest = min(heights), max(heights)
    if smallest <= 0:
        raise ValueError(
            f"a rendered vehicle height of {smallest} means nothing was rendered"
        )
    return float(largest) / float(smallest)
