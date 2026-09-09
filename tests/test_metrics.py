# Tests for the realism measures.
#
# metrics.py imports only cv2, numpy and PIL — no torch, no model — so these
# run anywhere those three are installed:
#
#     pytest tests/test_metrics.py -v
#
# The gallery-coherence tests deliberately reuse the fixtures from
# test_compositing.py. size_spread exists to put a number on the spread those
# tests already assert, and measuring it against a second set of cars would
# leave open the question of whether the two agree.

import numpy as np
import pytest
from PIL import Image

import compositing
import metrics
from test_compositing import (
    CAR_ASPECTS,
    backdrop,
    car_at_aspect,
    rendered_vehicle_height,
    silhouette,
)


def matted_square(size: int, ramp: float = 0.0) -> Image.Image:
    """
    A square cutout whose edge fades from clear to solid over `ramp` pixels.

    The ramp is computed from the distance to the edge rather than by blurring,
    because PIL's Gaussian is a stack of integer-width box blurs: at the small
    radii a matte actually has, doubling the radius does not double the width
    of the soft edge, and the scaling test below would then be measuring the
    fixture rather than the measure. A ramp of zero gives a hard binary edge.
    """
    inset = size // 5
    axis = np.arange(size, dtype=np.float32)
    to_edge = np.minimum(axis - inset, (size - inset - 1) - axis)
    signed = np.minimum(to_edge[None, :], to_edge[:, None])
    if ramp <= 0:
        alpha = np.where(signed >= 0, 255.0, 0.0)
    else:
        alpha = np.clip(signed / ramp + 0.5, 0.0, 1.0) * 255.0

    cutout = Image.new("RGBA", (size, size), (180, 40, 40, 255))
    cutout.putalpha(Image.fromarray(alpha.round().astype(np.uint8), mode="L"))
    return cutout


# ── Edge quality ───────────────────────────────────────────────────────────────

def test_a_binary_edge_has_no_fractional_alpha():
    """
    The defect this guards against: a measure that counted anything other than
    strictly-fractional alpha — silhouette pixels, or alpha at the extremes —
    would score a cut mask as well as a matted one, and Phase 3 would read as
    finished before it had been started.
    """
    score = metrics.edge_quality(matted_square(600, ramp=0.0))

    assert score.silhouette > 0, "no boundary was found to measure"
    assert score.fractional == 0
    assert score.ratio == 0.0


def test_a_matted_edge_scores_high():
    """
    The other half of the same defect: a band far wider than any real soft edge
    drags every score towards zero, so a genuine matte would score no better
    than the cut mask it replaced and the phase could not be shown to have done
    anything at all.
    """
    score = metrics.edge_quality(matted_square(600, ramp=6.0))

    assert score.ratio > 0.9, f"a fully matted edge scored {score.ratio:.3f}"
    assert score.fractional <= score.silhouette, "counted alpha outside the band"


def test_the_band_scales_with_the_image():
    """
    The defect: a band fixed in pixels holds the whole of a soft edge on a
    small image and only the middle of the same edge on a large one, so the
    identical matte scores differently at different resolutions. Phase 3's
    before and after are not shot at the same size — the point of matting is to
    work at native resolution — so a measure that moves with resolution would
    report the change as an improvement or a regression at random.
    """
    small = metrics.edge_quality(matted_square(1000, ramp=4.0))
    large = metrics.edge_quality(matted_square(2000, ramp=8.0))

    # Both sit mid-range on purpose. Saturated at 1.0 the two would agree even
    # with a fixed band, and the test would prove nothing.
    for score in (small, large):
        assert 0.2 < score.ratio < 0.8, f"fixture is not mid-range: {score.ratio:.3f}"
    assert abs(small.ratio - large.ratio) < 0.05, (
        f"the same edge scored {small.ratio:.3f} at 1000px and "
        f"{large.ratio:.3f} at 2000px"
    )


def test_a_transparent_margin_does_not_move_the_score():
    """
    The defect: counted over the whole image instead of over a band, the same
    edge scores differently according to how much empty space surrounds it. A
    cutout is trimmed and the frame it is placed into is not, so the same car
    would be reported twice, differently, for an edge nothing had touched.
    """
    tight = matted_square(600, ramp=3.0)
    padded = Image.new("RGBA", (1400, 1000), (0, 0, 0, 0))
    padded.paste(tight, (300, 200))

    assert metrics.edge_quality(padded).ratio == pytest.approx(
        metrics.edge_quality(tight).ratio, abs=0.01
    )


def test_an_image_with_no_boundary_scores_zero_rather_than_raising():
    """
    The defect: a finished composite is opaque everywhere and has no silhouette
    in it at all. Dividing the fractional count by an empty band raises
    ZeroDivisionError, which stops a whole batch of measurements on account of
    the one image that was the wrong thing to measure.
    """
    opaque = Image.new("RGBA", (200, 200), (200, 200, 205, 255))
    empty = Image.new("RGBA", (200, 200), (0, 0, 0, 0))

    assert metrics.edge_quality(opaque) == metrics.EdgeQuality(0, 0, 0.0)
    assert metrics.edge_quality(empty) == metrics.EdgeQuality(0, 0, 0.0)


def test_a_single_channel_mask_is_read_as_its_own_alpha():
    """
    The defect: `refine_alpha_mask` hands back an "L" mask, and converting one
    to RGBA fabricates a fully opaque alpha channel. Every mask measured that
    way scores zero — indistinguishable from the answer a hopelessly binary
    matte gives, so the mistake would look like a finding.
    """
    cutout = matted_square(600, ramp=6.0)

    assert metrics.edge_quality(cutout.getchannel("A")) == metrics.edge_quality(cutout)


# ── Horizon offset ─────────────────────────────────────────────────────────────

def test_horizon_offset_is_signed_by_which_horizon_sits_lower():
    """
    The defect: the sign is most of what this number is for. Phase 1 shifts the
    backdrop crop to close the offset, and with the convention reversed a shift
    in the wrong direction — one that doubles the mismatch — would be recorded
    as the correction working.
    """
    canvas_height = 1000

    # The vehicle's horizon further down the canvas than the backdrop's.
    assert metrics.horizon_offset(0.60, 0.50, canvas_height) == pytest.approx(100.0)
    assert metrics.horizon_offset(0.50, 0.60, canvas_height) == pytest.approx(-100.0)
    assert metrics.horizon_offset(0.55, 0.55, canvas_height) == pytest.approx(0.0)


def test_horizon_offset_is_pixels_rather_than_a_ratio():
    """
    The defect: returning the ratio difference would make a studio composite on
    its measured 960-tall canvas and a dealer backdrop at whatever they
    uploaded look equally wrong when one is half the error of the other in the
    only unit a viewer sees.
    """
    assert metrics.horizon_offset(0.60, 0.50, 960) == pytest.approx(96.0)
    assert metrics.horizon_offset(0.60, 0.50, 1920) == pytest.approx(192.0)


# ── Gallery coherence ──────────────────────────────────────────────────────────

def test_size_spread_is_one_when_every_photograph_renders_one_size():
    """
    The defect: 1.000 is the figure the project already claims, so anything
    that returns 0.0 or 1.0-by-luck for a uniform gallery would let a
    regression through while still printing the number the report quotes.
    """
    assert metrics.size_spread([320.0, 320.0, 320.0]) == pytest.approx(1.0)
    assert metrics.size_spread([320.0]) == pytest.approx(1.0)


def test_size_spread_reports_the_worst_pair_rather_than_the_average():
    """
    The defect: a mean or a standard deviation buries one badly sized
    photograph among a dozen good ones. The odd tile is the one a dealer
    scrolling the gallery actually notices, so the measure has to be driven by
    it and not diluted by its neighbours.
    """
    assert metrics.size_spread([100, 100, 100, 100, 150]) == pytest.approx(1.5)


def test_size_spread_refuses_a_gallery_nothing_rendered_in():
    """
    The defect: a photograph that produced no vehicle at all is a failed job,
    not an incoherent gallery. Dividing by it yields infinity, and an infinity
    in the evidence table reads as a measurement rather than as a missing one.
    """
    with pytest.raises(ValueError):
        metrics.size_spread([300, 0, 280])
    with pytest.raises(ValueError):
        metrics.size_spread([])


def test_size_spread_agrees_with_the_gallery_assertion_it_reports_on():
    """
    The defect this exists to prevent: a coherence number defined differently
    from the assertion in test_compositing.py would let the two disagree about
    a gallery neither of them changed, and then neither figure could be quoted.
    The heights compose() now reports must give the same answer as hunting for
    the car's colour in the finished frame, which is how the spread has been
    measured until now.
    """
    measured, reported = [], []
    for angle, aspect in CAR_ASPECTS.items():
        result, meta = compositing.compose(
            car_at_aspect(aspect), backdrop(1600, 1200), angle=angle
        )
        measured.append(rendered_vehicle_height(result))
        reported.append(meta["vehicle_height_px"])

    assert metrics.size_spread(reported) == pytest.approx(
        metrics.size_spread(measured), abs=0.02
    )
    assert metrics.size_spread(reported) < 1.10


def test_size_spread_across_the_studio_gallery_is_still_one():
    """
    The measure earning its keep: the 1.000 across angles that REALISM_PLAN.md
    says must stay there, taken from the job record rather than from a test
    that reaches into the pixels. If a later phase quietly reintroduces
    per-photograph scaling, this is the number that moves.
    """
    backdrop_image, preset = compositing.load_studio_backdrop("studio_full")
    assert backdrop_image is not None, "studio-full.png is missing from assets"

    heights = [
        compositing.compose(silhouette(aspect), backdrop_image, preset, angle=angle)[1][
            "vehicle_height_px"
        ]
        for angle, aspect in CAR_ASPECTS.items()
    ]

    assert metrics.size_spread(heights) == pytest.approx(1.0, abs=0.03)


# ── What compose() now reports ─────────────────────────────────────────────────

def test_compose_reports_the_rendered_height_and_the_contact_line():
    """
    The defect: compose() knew the fitted height and the line the car stands on
    and threw both away, so gallery coherence could only be recovered by
    searching the finished frame for the vehicle's colour — which a test can do
    against a synthetic red block and a job record cannot do at all.
    """
    canvas_h = 1200
    result, meta = compositing.compose(car_at_aspect(3.13), backdrop(1600, canvas_h))

    assert meta["vehicle_height_px"] == pytest.approx(
        rendered_vehicle_height(result), abs=4
    )
    # DEALER_BACKDROP stands the vehicle on 0.84 of the canvas.
    assert meta["contact_y_px"] == pytest.approx(canvas_h * 0.84, abs=2)


def test_the_contact_line_follows_the_measured_platform():
    """
    The defect: reporting the canvas bottom, or the vehicle's own lowest row,
    instead of the ground line would agree with the dealer backdrop by
    coincidence and be wrong on the one scene whose platform was measured by
    hand — which is the scene Phase 1 will align its horizon against.
    """
    _, meta = compositing.compose(
        car_at_aspect(3.13), backdrop(2000, 1500), compositing.STUDIO_FULL
    )

    expected = 960 * compositing.STUDIO_FULL.platform_contact_y_ratio
    assert meta["contact_y_px"] == pytest.approx(expected, abs=2)


def test_the_new_keys_are_purely_additive():
    """
    The defect: the job record is written from this dictionary and the client
    reads it, so renaming or dropping a key to make room for the two new ones
    would break every existing reader while the tests for the new keys carried
    on passing.
    """
    _, meta = compositing.compose(car_at_aspect(3.13), backdrop(1600, 1200))

    assert {
        "backdrop",
        "backdrop_style",
        "output_size",
        "ground_aligned",
        "shadow_applied",
        "colour_matched",
        "shot_angle",
        "height_normalised",
        "reflection_applied",
    } <= set(meta)
    assert meta["output_size"] == {"width": 1600, "height": 1200}
    assert meta["height_normalised"] is True
