"""Placing a cut-out vehicle into a scene so it reads as photographed in it.

The compositing here is Suraj Purella's, from the Auto_pivot_Scaling branch
(`pipeline_service.py`). His branch replaced the whole application with a
standalone processing service, so rather than merging it the compositing was
lifted out and the platform left alone. The geometry, the shadow construction
and the LAB matching are his; the packaging and the dealer-backdrop path are
the adaptation.

A straight paste fails for three reasons, and this addresses each:

  * The mask is computed at 1024x1024 and stretched over a 3000-pixel
    photograph, which leaves soft, haloed edges. `refine_alpha_mask` closes
    pinholes, pulls the edge in a pixel and feathers it.
  * Nothing anchors the vehicle to the floor, so it floats. `build_shadow`
    lays down an ambient pool and a tighter contact shadow, derived from the
    vehicle's own silhouette rather than a generic ellipse.
  * The photograph and the backdrop were lit differently. `match_colour`
    nudges the vehicle towards the backdrop's LAB mean, weakly and clamped —
    strongly enough to sit, not so strongly that the paint changes colour,
    which would matter on a listing.

Two further problems show up only once a whole listing is processed rather
than a single photograph, and this addresses those as well:

  * Every shot was scaled to fill the available box, so the car changed size
    from one gallery tile to the next — a head-on shot was enlarged half as
    much again as a side-on one, and a dealer flipping through the gallery saw
    what looked like a different car. `_fit_vehicle` now scales by the
    vehicle's visible height instead, which is the one dimension a turntable
    does not change. See `REFERENCE_VEHICLE_ASPECT`.
  * The studio platform is a polished raised base and nothing was reflected in
    it, which is the cue that gives away a composite even when the shadow is
    right. `_build_reflection` mirrors the vehicle below its contact line,
    fading and clipped to the platform.

The geometry, the shadow construction and the LAB matching remain Suraj's; the
height normalisation, the angle profiles and the reflection extend them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("autopivot.compositing")

BACKGROUND_DIR = Path(__file__).resolve().parent / "assets" / "backgrounds"

# A dealer backdrop can be any size; this bounds the working canvas so a large
# upload cannot turn one job into a memory problem.
MAX_CANVAS_WIDTH = 2400

# The shot angles the compositor understands. This mirrors the vocabulary the
# listing images carry in `detected_angle`; anything outside it is treated as
# "unknown" rather than rejected, because a classifier gaining a new label
# should not start failing jobs.
VehicleAngle = Literal["front", "front_quarter", "side", "rear_quarter", "rear"]

# The widest a passenger car ever projects, as a ratio of its own height.
#
# This is the constant that fixes the gallery. A car turning on the spot barely
# changes apparent height — the roof stays roughly the same distance from the
# camera, so only the near roof edge moves and that is worth under ten per cent
# — while its projected length collapses by a factor of nearly three. For a
# 4.70 x 1.83 x 1.45 m sedan the projected length runs 4.70 m side-on, peaks
# near 5.01 m at three-quarter where the body's width starts to add to its
# length, and falls to 1.83 m head-on: 3.24, 3.46 and 1.26 times the height.
# Sizing every shot to a height rather than to whichever edge of the box it hit
# first therefore renders one car at one size whatever way it is facing, and
# does so without any knowledge of the other images in the listing.
#
# The value is the wide end of that range rather than the middle, so that the
# widest angle is the one that just fills the preset's width budget. That is
# also what keeps this change quiet: a side-on hero shot comes out the size it
# always did, and it is the head-on and quarter shots — the ones that used to
# be enlarged to half again their proper size — that move to meet it.
REFERENCE_VEHICLE_ASPECT = 3.2

# How far past the preset's own width budget a height-normalised vehicle may
# run before the old fill-the-box scaling is used instead. A long ute, a car
# with a bike rack, or a generously cropped side-on shot sits a little wider
# than the reference car and should not be shrunk for it; something half as
# wide again is not a passenger car in a normal shot, and the old rule handles
# it more gracefully than a fixed height would.
MAX_WIDTH_OVERRUN = 1.12

# Nothing may be scaled to touch the frame edge, whatever the preset asks for.
MAX_CANVAS_FILL = 0.96

# How much a cutout may be clamped below its target height and still count as
# normalised. A long car gives up a few per cent to stay on the platform and
# should keep the consistent sizing; a panorama gives up more than half and is
# not a car, so it falls back to the older fill-the-box rule.
NORMALISE_CLAMP_FLOOR = 0.75


@dataclass(frozen=True)
class BackdropPreset:
    """
    How a vehicle sits in a particular scene.

    All geometry is expressed as a ratio of the canvas, so one preset holds
    whatever size the scene is rendered at.
    """

    key: str
    label: str
    filename: str = ""
    # "ground" stands the vehicle on a surface; "center" places it in frame
    # without a contact point, for close-ups shot against a wall.
    placement: str = "ground"
    ground_y_ratio: float = 0.84
    # x1, y1, x2, y2 of the display base, as canvas ratios. Present only for
    # scenes measured by hand — it clips shadows to the platform surface.
    platform_box: tuple[float, float, float, float] | None = None
    platform_contact_y_ratio: float | None = None
    vehicle_width_ratio: float = 0.72
    vehicle_height_ratio: float = 0.60
    # How strongly the floor mirrors the vehicle, 0 for not at all. Off by
    # default because it is only correct on a surface we have measured and know
    # to be polished: a dealer's own backdrop may be carpet, gravel or a
    # workshop floor, and reflecting a car in gravel looks worse than not
    # reflecting it at all.
    reflection_strength: float = 0.0
    # None means "use the backdrop's own dimensions", which is what a dealer
    # upload wants — their scene, their resolution.
    output_size: tuple[int, int] | None = None


# Measured by Suraj Purella against the rendered showroom. The reference was
# 1448x1086 and the output is 1280x960; both are 4:3, so the ratios carry over
# without distortion.
STUDIO_FULL = BackdropPreset(
    key="studio_full",
    label="AutoPivot Studio — Full Car",
    filename="studio-full.png",
    placement="ground",
    ground_y_ratio=0.755,
    platform_box=(0.105, 0.598, 0.875, 0.820),
    platform_contact_y_ratio=0.755,
    vehicle_width_ratio=0.86,
    vehicle_height_ratio=0.54,
    # The only surface in the asset set we have measured and can see is
    # polished. Kept well under half strength: the platform top is mid-grey
    # concrete, not glass, and an over-bright mirror image reads as a second
    # car rather than as a reflection.
    reflection_strength=0.30,
    output_size=(1280, 960),
)

STUDIO_CLOSEUP = BackdropPreset(
    key="studio_closeup",
    label="AutoPivot Studio — Close-up",
    filename="studio-closeup.png",
    placement="center",
    ground_y_ratio=0.82,
    vehicle_width_ratio=0.86,
    vehicle_height_ratio=0.78,
    output_size=(1280, 960),
)

STUDIO_PRESETS: dict[str, BackdropPreset] = {
    STUDIO_FULL.key: STUDIO_FULL,
    STUDIO_CLOSEUP.key: STUDIO_CLOSEUP,
}

# What a dealership's own backdrop gets. No measured platform, so shadows are
# not clipped and the vehicle stands on a nominal ground line.
DEALER_BACKDROP = BackdropPreset(key="custom", label="Dealership backdrop")


@dataclass(frozen=True)
class _AngleProfile:
    """
    What the shot angle changes about how a vehicle meets the floor.

    The silhouette already carries the vehicle's outline, so these are
    multipliers on the existing shadow rather than replacements for it. The
    defaults are all neutral, which is what an unknown angle gets: a caller
    that passes nothing must land on exactly the geometry that shipped.
    """

    # Multiplies how far the shadow pool reaches into the frame. The pool is
    # the vehicle's footprint foreshortened, and the footprint is 1.8 m deep
    # seen side-on against 4.7 m deep seen head-on, so a head-on shadow has to
    # be markedly deeper than a side-on one at the same silhouette height.
    shadow_depth: float = 1.0
    # Multiplies the pool's width. Barely moves: the silhouette is already
    # narrow head-on and wide side-on, so most of the width is handled for us.
    shadow_width: float = 1.0
    # How much of the silhouette's own weight imbalance is corrected out of the
    # horizontal placement. See `_mass_skew` for why an oblique shot needs it
    # and a symmetrical one does not.
    mass_shift: float = 0.0


_NEUTRAL_PROFILE = _AngleProfile()

# Depths are pinned to the footprint ratio computed above (4.7 / 1.8 = 2.6),
# then pulled towards neutral: the pool that shipped is a stylised ambient one
# rather than a true cast shadow, and stretching it to the full physical depth
# on a head-on shot turns it into a puddle.
_ANGLE_PROFILES: dict[str, _AngleProfile] = {
    "front": _AngleProfile(shadow_depth=2.00, shadow_width=1.06),
    "front_quarter": _AngleProfile(shadow_depth=1.30, shadow_width=1.02, mass_shift=0.5),
    "side": _AngleProfile(shadow_depth=0.85, shadow_width=1.00),
    "rear_quarter": _AngleProfile(shadow_depth=1.30, shadow_width=1.02, mass_shift=0.5),
    "rear": _AngleProfile(shadow_depth=2.00, shadow_width=1.06),
}


def _angle_profile(angle: str | None) -> _AngleProfile:
    """The profile for a shot angle, neutral for None or anything unrecognised."""
    if angle is None:
        return _NEUTRAL_PROFILE
    profile = _ANGLE_PROFILES.get(angle)
    if profile is None:
        logger.debug("Unrecognised shot angle '%s'; composing without an angle", angle)
        return _NEUTRAL_PROFILE
    return profile


def load_studio_backdrop(key: str) -> tuple[Image.Image, BackdropPreset] | None:
    """Open a built-in scene, or None if the key is unknown or the file is absent."""
    preset = STUDIO_PRESETS.get(key)
    if preset is None:
        return None
    path = BACKGROUND_DIR / preset.filename
    if not path.exists():
        logger.warning("Studio backdrop '%s' is missing from %s", preset.filename, BACKGROUND_DIR)
        return None
    try:
        return Image.open(path).convert("RGBA"), preset
    except OSError as exc:
        logger.warning("Studio backdrop '%s' could not be opened: %s", preset.filename, exc)
        return None


# ── Mask cleanup ───────────────────────────────────────────────────────────────

def refine_alpha_mask(mask: Image.Image) -> Image.Image:
    """
    Tidy a segmentation mask: close pinholes, pull the edge in, feather it.

    The erode is what removes the light fringe of background that the model
    leaves around the silhouette — visible as a halo once the vehicle sits on a
    darker scene. Kept to one pixel: more starts eating wing mirrors and aerials.
    """
    alpha = np.array(mask.convert("L"), dtype=np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    alpha = cv2.erode(alpha, kernel, iterations=1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.65)
    # Snap the near-extremes so the cutout has genuinely clear and genuinely
    # solid regions rather than a wash of almost-zero alpha.
    alpha[alpha <= 2] = 0
    alpha[alpha >= 253] = 255
    return Image.fromarray(alpha, mode="L")


def trim_transparent(cutout: Image.Image) -> Image.Image:
    """Crop to the visible vehicle, keeping a 2px margin."""
    cutout = cutout.convert("RGBA")
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    bbox = Image.fromarray((alpha > 4).astype(np.uint8) * 255, mode="L").getbbox()
    if bbox is None:
        return cutout
    left, top, right, bottom = bbox
    return cutout.crop((
        max(0, left - 2),
        max(0, top - 2),
        min(cutout.width, right + 2),
        min(cutout.height, bottom + 2),
    ))


# ── Geometry ───────────────────────────────────────────────────────────────────

def _visible_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha > 6)
    if xs.size == 0 or ys.size == 0:
        return 0, 0, image.width, image.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _contact_y(vehicle: Image.Image) -> int:
    """
    The line the tyres sit on.

    Deliberately not the lowest opaque pixel: a single stray row of mask —
    a shadow remnant from the original ground, a segmentation spike — would
    lift the whole car off the floor. Taking the 0.97 quantile of each column's
    lowest solid pixel ignores those without losing the real contact line.
    """
    mask = np.array(vehicle.getchannel("A"), dtype=np.uint8) >= 96
    bottoms = [
        int(ys[-1])
        for x in range(mask.shape[1])
        if (ys := np.flatnonzero(mask[:, x])).size
    ]
    if not bottoms:
        return _visible_bounds(vehicle)[3]
    return int(round(float(np.quantile(np.asarray(bottoms, dtype=np.float32), 0.97))))


def _canvas_size(backdrop: Image.Image, preset: BackdropPreset) -> tuple[int, int]:
    if preset.output_size is not None:
        return preset.output_size
    width, height = backdrop.size
    if width > MAX_CANVAS_WIDTH:
        height = max(1, round(height * MAX_CANVAS_WIDTH / width))
        width = MAX_CANVAS_WIDTH
    return width, height


def _fit_backdrop(backdrop: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cover the canvas without distorting: scale to fill, then centre-crop."""
    target_w, target_h = size
    source = backdrop.convert("RGBA")
    scale = max(target_w / source.width, target_h / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _fit_vehicle(
    cutout: Image.Image, preset: BackdropPreset, size: tuple[int, int]
) -> tuple[Image.Image, bool]:
    """
    Scale the cutout to the scene. Returns the vehicle and whether height
    normalisation was used rather than the older fill-the-box rule.

    Filling the box independently per photograph is what made a listing's
    gallery look like several different cars. A head-on shot is roughly as wide
    as it is tall, so it ran out of height first and was enlarged until it
    filled the frame vertically; a side-on shot of the same car is nearly three
    times as wide as it is tall, so it ran out of width first and was left
    around half that size. Flicking through the gallery, the car grew and shrank.

    Scaling to a target height fixes it without needing to see the other
    photographs, because height is the dimension a turntable leaves alone. The
    target is the height the reference car would have been given under the old
    rule, so a side-on shot — the usual hero image — comes out the size it
    always did and it is the other angles that move to meet it.
    """
    canvas_w, canvas_h = size
    if preset.platform_box:
        # Scale against the display base rather than the whole frame, so the
        # car sits on the platform instead of overhanging it.
        platform_width = canvas_w * (preset.platform_box[2] - preset.platform_box[0])
        max_width = platform_width * preset.vehicle_width_ratio
        # The platform edge is a hard limit however wide the cutout is: a car
        # overhanging the base reads as floating, which is the failure the
        # platform was measured to avoid in the first place.
        limit_width = min(platform_width, max_width * MAX_WIDTH_OVERRUN)
    else:
        max_width = canvas_w * preset.vehicle_width_ratio
        limit_width = min(canvas_w * MAX_CANVAS_FILL, max_width * MAX_WIDTH_OVERRUN)
    max_height = canvas_h * preset.vehicle_height_ratio
    limit_height = canvas_h * MAX_CANVAS_FILL

    fill_scale = min(max_width / cutout.width, max_height / cutout.height)
    scale, normalised = fill_scale, False

    left, top, right, bottom = _visible_bounds(cutout)
    visible_w, visible_h = right - left, bottom - top
    if visible_w > 0 and visible_h > 0:
        target_height = min(max_height, max_width / REFERENCE_VEHICLE_ASPECT)
        candidate = target_height / visible_h

        # Clamped to the limits rather than abandoned at them. The limits are
        # measured against the whole image rather than the visible box on
        # purpose: `compose` trims first so the two are within a couple of
        # pixels, and being conservative means an untrimmed cutout is reined in
        # rather than overflowing the frame.
        clamped = min(
            candidate,
            limit_width / cutout.width,
            limit_height / cutout.height,
        )

        # A binary accept-or-abandon here put a cliff exactly where cars are
        # most common. A genuine side-on shot runs about 3.5 wide to 1 tall
        # once wheels and mirrors are in frame — a little past the reference
        # 3.2 — so it failed the width limit by a hair and dropped all the way
        # back to fill-the-box, rendering some twelve per cent smaller than the
        # same car at every other angle. That is the size step this whole
        # function exists to remove. Clamping keeps it within a per cent or two.
        #
        # The ratio is what still separates a car from something that is not
        # one: a panorama or a badly cropped strip clamps to a small fraction
        # of its target, and is better served by the old rule than by being
        # forced to a car's height.
        if clamped >= candidate * NORMALISE_CLAMP_FLOOR:
            scale, normalised = clamped, True

    return (
        cutout.resize(
            (max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))),
            Image.Resampling.LANCZOS,
        ),
        normalised,
    )


def _mass_skew(vehicle: Image.Image) -> float:
    """
    How far the silhouette's weight sits from the middle of its bounding box,
    as a fraction of the bounding box's width. Positive means weight to the right.
    """
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    columns = alpha.sum(axis=0, dtype=np.float64)
    total = columns.sum()
    left, _, right, _ = _visible_bounds(vehicle)
    width = right - left
    if total <= 0 or width <= 0:
        return 0.0
    centroid = float((columns * np.arange(columns.size, dtype=np.float64)).sum() / total)
    return (centroid - (left + right) / 2.0) / width


def _vehicle_position(
    vehicle: Image.Image,
    preset: BackdropPreset,
    size: tuple[int, int],
    profile: _AngleProfile = _NEUTRAL_PROFILE,
) -> tuple[int, int, int]:
    """Return where to paste the vehicle, and the y of the ground line."""
    canvas_w, canvas_h = size
    left, top, right, bottom = _visible_bounds(vehicle)

    # Centring the bounding box is right for a symmetrical shot and slightly
    # wrong for an oblique one. A car standing in the middle of the turntable
    # projects asymmetrically: the near end is magnified and reaches further
    # from the centre than the far end does, so its bounding box is skewed
    # towards the camera-side end. Centring that box therefore pushes the car
    # itself away from the middle of the platform, and across a gallery the car
    # appears to slide sideways as it turns. Nudging back towards the heavy end
    # by a fraction of the silhouette's own weight imbalance undoes most of it.
    # Only the quarter angles carry a non-zero shift; front, side and rear are
    # symmetrical enough that the correction would be noise.
    skew = _mass_skew(vehicle) * profile.mass_shift if profile.mass_shift else 0.0
    offset = skew * (right - left)

    if preset.platform_box:
        platform_centre_x = canvas_w * (preset.platform_box[0] + preset.platform_box[2]) / 2
        x = round(platform_centre_x - (left + right) / 2 + offset)
    else:
        x = round(canvas_w / 2 - (left + right) / 2 + offset)

    if preset.placement == "center":
        y = round(canvas_h * 0.52 - (top + bottom) / 2)
        return int(x), int(y), min(canvas_h - 1, int(y + bottom))

    contact = _contact_y(vehicle) if preset.platform_box else bottom
    ratio = (
        preset.platform_contact_y_ratio
        if preset.platform_contact_y_ratio is not None
        else preset.ground_y_ratio
    )
    ground_y = round(canvas_h * ratio)
    return int(x), int(round(ground_y - contact)), int(ground_y)


def _platform_mask(
    preset: BackdropPreset, size: tuple[int, int], feather: float = 0.0
) -> Image.Image | None:
    """
    An ellipse over the display base, so shadows cannot spill off its edge.

    `feather` softens that edge. Shadows leave it at zero — they are faint by
    the time they reach the rim, so the hard cut never showed — but a
    reflection is brightest exactly where the platform ends, and an unfeathered
    clip slices it off with a razor edge that looks like a rendering fault.
    """
    if not preset.platform_box:
        return None
    canvas_w, canvas_h = size
    x1, y1, x2, y2 = preset.platform_box
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(
        (
            round(canvas_w * x1), round(canvas_h * y1),
            round(canvas_w * x2), round(canvas_h * y2),
        ),
        fill=255,
    )
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


# ── Shadows ────────────────────────────────────────────────────────────────────

def _build_shadow(
    alpha: Image.Image,
    vehicle_x: int,
    ground_y: int,
    opacity: float,
    blur: float,
    height_ratio: float,
    width_scale: float,
) -> tuple[Image.Image, tuple[int, int]]:
    """
    Squash the vehicle's own silhouette into a shadow on the floor.

    Using the silhouette rather than an ellipse is what makes it read: the
    shadow narrows at the bonnet and widens at the wheel arches the way the
    car does.
    """
    source = alpha.convert("L")
    width = max(1, round(source.width * width_scale))
    height = max(4, round(source.height * height_ratio))
    compressed = source.resize((width, height), Image.Resampling.LANCZOS)

    # Pad before blurring so the falloff is not clipped at the edges.
    padding = max(2, round(blur * 2))
    mask = Image.new("L", (width + padding * 2, height + padding * 2), 0)
    mask.paste(compressed, (padding, padding))
    mask = mask.point(lambda v: int(v * opacity)).filter(ImageFilter.GaussianBlur(blur))

    shadow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    shadow.putalpha(mask)
    return shadow, (
        vehicle_x + (source.width - width) // 2 - padding,
        ground_y - height // 2 - padding - 2,
    )


def _shadows(
    alpha: Image.Image,
    vehicle_x: int,
    ground_y: int,
    profile: _AngleProfile = _NEUTRAL_PROFILE,
) -> list[tuple[Image.Image, tuple[int, int]]]:
    """
    Ambient pool first, then the tighter darker contact shadow over it.

    The profile multipliers are what make a side-on shadow long and shallow and
    a head-on one short and deep; with the neutral profile the numbers are the
    ones that shipped.
    """
    return [
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.14, 24, 0.14 * profile.shadow_depth, 1.04 * profile.shadow_width,
        ),
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.32, 12, 0.075 * profile.shadow_depth, 0.90 * profile.shadow_width,
        ),
    ]


# ── Reflection ─────────────────────────────────────────────────────────────────

# How far the mirror image is squashed towards the contact line. A reflection
# in a floor is foreshortened by the same perspective that flattens the
# platform into an ellipse, so it is nothing like as tall as the vehicle.
REFLECTION_SQUASH = 0.42


def _build_reflection(
    vehicle: Image.Image, contact_y: int, strength: float, blur: float
) -> Image.Image | None:
    """
    A soft mirror image of the vehicle, to be placed with its top on the
    contact line. None when there is nothing worth reflecting.

    Only the body above the contact line is mirrored. Reflecting the whole
    cutout would fold any mask spill below the tyres — the remains of the
    original ground shadow, usually — back up into the floor as a dark smear,
    and it wastes work on rows that end up under the car anyway.
    """
    if strength <= 0:
        return None
    contact_y = min(contact_y, vehicle.height)
    if contact_y < 8:
        return None

    mirrored = vehicle.crop((0, 0, vehicle.width, contact_y)).transpose(
        Image.Transpose.FLIP_TOP_BOTTOM
    )
    height = max(4, round(mirrored.height * REFLECTION_SQUASH))
    mirrored = mirrored.resize((mirrored.width, height), Image.Resampling.LANCZOS)

    # The fade is deliberately convex rather than linear. A reflection in a
    # surface that is not a mirror loses contrast fastest close to the contact
    # point, and a straight ramp leaves a visible band halfway down where the
    # eye reads a second, upside-down car.
    alpha = np.array(mirrored.getchannel("A"), dtype=np.float32)
    fade = (1.0 - np.linspace(0.0, 1.0, height, dtype=np.float32)) ** 1.6
    alpha *= strength * fade[:, None]

    faded = Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), mode="L")
    if blur > 0:
        # Only the alpha is blurred. Blurring the colour as well would drag the
        # cutout's transparent margin — black on a synthesised cutout, the
        # original photograph's background on a real one — into the reflection's
        # edge, and neither belongs on the platform.
        faded = faded.filter(ImageFilter.GaussianBlur(blur))
    mirrored.putalpha(faded)
    return mirrored


def _reflects(preset: BackdropPreset) -> bool:
    """
    Whether this scene gets a reflection.

    Three conditions, all of them refusals rather than permissions. The preset
    has to ask for one; there has to be a floor at all, which a close-up shot
    against a wall does not have; and the platform has to have been measured,
    because the clip that keeps the reflection on the polished surface is
    derived from that measurement and a dealer's own backdrop has none.
    """
    return (
        preset.reflection_strength > 0
        and preset.placement == "ground"
        and preset.platform_box is not None
    )


def _placement(
    layer_size: tuple[int, int], position: tuple[int, int], canvas_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], tuple[int, int]] | None:
    """
    Where a layer actually lands, once any overhang is cropped away: the box to
    take from the layer and the point on the canvas to put it. None when the
    layer misses the canvas entirely.

    Shadows are wider than the vehicle and padded by twice the blur radius, so
    on a small backdrop the destination goes negative or runs past the right or
    bottom edge. Pillow's own handling of that is version-dependent, so the
    arithmetic is done here.
    """
    layer_w, layer_h = layer_size
    canvas_w, canvas_h = canvas_size
    x, y = position

    left, top = max(0, -x), max(0, -y)
    if left >= layer_w or top >= layer_h:
        return None

    x, y = max(0, x), max(0, y)
    if x >= canvas_w or y >= canvas_h:
        return None

    right = min(layer_w, left + canvas_w - x)
    bottom = min(layer_h, top + canvas_h - y)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom), (x, y)


def _alpha_composite_at(
    canvas: Image.Image, layer: Image.Image, position: tuple[int, int]
) -> None:
    """alpha_composite that tolerates a layer hanging off any edge."""
    placed = _placement(layer.size, position, canvas.size)
    if placed is None:
        return
    box, destination = placed
    if box != (0, 0, layer.width, layer.height):
        layer = layer.crop(box)
    canvas.alpha_composite(layer, destination)


def _composite_clipped(
    canvas: Image.Image,
    layer: Image.Image,
    position: tuple[int, int],
    clip: Image.Image | None,
) -> None:
    """
    Composite a layer with its alpha multiplied by a full-canvas clip mask.

    Only the rectangle the layer actually occupies is materialised. This used
    to stage a whole extra RGBA canvas per layer, which on a 2400px dealer
    backdrop is seventeen megabytes for the sake of a shadow a fraction of that
    size — and there are several layers per job.
    """
    if clip is None:
        _alpha_composite_at(canvas, layer, position)
        return

    placed = _placement(layer.size, position, canvas.size)
    if placed is None:
        return
    box, (x, y) = placed
    # crop always returns a new image, so the caller's layer is never mutated
    # by the putalpha below.
    patch = layer.crop(box)

    patch_alpha = np.array(patch.getchannel("A"), dtype=np.float32)
    clip_alpha = np.array(
        clip.crop((x, y, x + patch.width, y + patch.height)), dtype=np.float32
    ) / 255.0
    patch.putalpha(
        Image.fromarray(np.clip(patch_alpha * clip_alpha, 0, 255).astype(np.uint8), mode="L")
    )
    canvas.alpha_composite(patch, (x, y))


# ── Colour ─────────────────────────────────────────────────────────────────────

def _backdrop_patch(backdrop: Image.Image, x: int, y: int, width: int, height: int) -> np.ndarray:
    """The region of the scene the vehicle will occupy, plus a margin."""
    margin_x, margin_y = max(8, width // 10), max(8, height // 10)
    return np.array(
        backdrop.crop((
            max(0, x - margin_x),
            max(0, y - margin_y),
            min(backdrop.width, x + width + margin_x),
            min(backdrop.height, y + height + margin_y),
        )).convert("RGB"),
        dtype=np.uint8,
    )


def match_colour(
    vehicle: Image.Image, backdrop: Image.Image, x: int, y: int
) -> Image.Image:
    """
    Nudge the vehicle towards the scene's lighting. Weak and clamped on purpose.

    Lightness moves at 12% of the difference and no more than 18 LAB units;
    the colour axes at 15% and no more than 5. A dealer's photograph has to
    stay the colour the car actually is, so this corrects for the light it was
    shot under and stops well short of repainting it.
    """
    rgba = np.array(vehicle.convert("RGBA"), dtype=np.uint8)
    opaque = rgba[:, :, 3] > 24
    patch = _backdrop_patch(backdrop, x, y, vehicle.width, vehicle.height)
    if not np.any(opaque) or patch.size == 0:
        return vehicle

    vehicle_lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    backdrop_lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    vehicle_mean = vehicle_lab[opaque].mean(axis=0)
    backdrop_mean = backdrop_lab.reshape(-1, 3).mean(axis=0)

    vehicle_lab[:, :, 0] += np.clip((backdrop_mean[0] - vehicle_mean[0]) * 0.12, -18, 18)
    vehicle_lab[:, :, 1:3] += np.clip((backdrop_mean[1:3] - vehicle_mean[1:3]) * 0.15, -5, 5)

    rgba[:, :, :3] = cv2.cvtColor(
        np.clip(vehicle_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB
    )
    return Image.fromarray(rgba, mode="RGBA")


# ── Entry point ────────────────────────────────────────────────────────────────

def compose(
    cutout: Image.Image,
    backdrop: Image.Image,
    preset: BackdropPreset = DEALER_BACKDROP,
    *,
    angle: VehicleAngle | str | None = None,
) -> tuple[Image.Image, dict]:
    """
    Place a cut-out vehicle onto a backdrop.

    Returns the finished image and what was done to it, for the job record.
    The cutout is expected to have had its plates treated already: it is
    rescaled here, so any coordinates taken from it beforehand stop being valid.

    `angle` is the shot angle, if something upstream knows it. It refines
    horizontal placement and the shape of the shadow pool; passing nothing, or
    a label this module does not recognise, composes exactly as it would have
    without the argument. It is keyword-only so that the two- and three-
    positional-argument calls that already exist keep working untouched.
    """
    cutout = trim_transparent(cutout.convert("RGBA"))
    size = _canvas_size(backdrop, preset)
    canvas = _fit_backdrop(backdrop, size)
    profile = _angle_profile(angle)

    vehicle, normalised = _fit_vehicle(cutout, preset, size)
    x, y, ground_y = _vehicle_position(vehicle, preset, size, profile)
    vehicle = match_colour(vehicle, canvas, x, y)

    result = canvas.copy()
    shadowed = preset.placement == "ground"
    reflected = False
    if shadowed:
        clip = _platform_mask(preset, size)
        if _reflects(preset):
            # Under the shadows on purpose. Both live in the floor, and letting
            # the contact shadow darken the reflection where the tyres meet the
            # platform is what stops the mirror image looking like a decal
            # stuck on underneath the car.
            reflection = _build_reflection(
                vehicle,
                ground_y - y,
                preset.reflection_strength,
                blur=max(1.0, size[1] * 0.0035),
            )
            if reflection is not None:
                _composite_clipped(
                    result,
                    reflection,
                    (x, ground_y),
                    _platform_mask(preset, size, feather=size[1] * 0.006),
                )
                reflected = True
        for shadow, position in _shadows(vehicle.getchannel("A"), x, ground_y, profile):
            _composite_clipped(result, shadow, position, clip)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(vehicle, (x, y), vehicle.getchannel("A"))
    result.alpha_composite(layer)

    return result, {
        "backdrop": preset.label,
        "backdrop_style": preset.key,
        "output_size": {"width": size[0], "height": size[1]},
        "ground_aligned": shadowed,
        "shadow_applied": shadowed,
        "colour_matched": True,
        "shot_angle": angle,
        "height_normalised": normalised,
        "reflection_applied": reflected,
    }
