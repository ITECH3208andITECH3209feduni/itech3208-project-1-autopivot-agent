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
import math
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

# A representative passenger vehicle's side-on projected length, as a ratio
# of its own height.
#
# This is the constant that fixes the gallery. A car turning on the spot barely
# changes apparent height — the roof stays roughly the same distance from the
# camera, so only the near roof edge moves and that is worth under ten per cent
# — while its projected length collapses by a factor of nearly three. Sizing
# every shot to a height rather than to whichever edge of the box it hit first
# therefore renders one car at one size whatever way it is facing, and does so
# without any knowledge of the other images in the listing.
#
# This used to be pinned to the wide end of one body style — a 4.70 x 1.83 x
# 1.45 m sedan, 3.24 side-on — on the reasoning that the widest angle should
# be the one that just fills the preset's width budget. That reasoning holds
# for a sedan; it does not for the rest of a dealer's actual stock. A hatchback
# runs nearer 2.9, an SUV or a minivan nearer 2.7–2.9 — shorter and, just as
# importantly, TALLER, so the same target height yields a visibly narrower
# car.
#
# Lowering this constant is the only lever that grows those boxier vehicles,
# but it is a shared lever: every angle of the SAME car is sized off this one
# number (see the gallery-consistency reasoning above), including the side-on
# hero shot, and that shot is already clamped flush to the platform's own
# measured edge (see MAX_WIDTH_OVERRUN) once its own silhouette — mirrors and
# wheel arches included, nearer 3.55–3.6:1 than any body panel's own ratio —
# runs past this reference. Push the reference down to flatter a minivan and
# the hero shot's clamp gets *tighter* relative to the target height every
# other angle is now reaching for, and the gallery starts drifting apart again
# in the other direction. 3.14 is the lowest value that keeps every angle of
# `tests/test_compositing.py::test_a_car_shaped_cutout_is_also_one_size_at_every_angle`
# within its 3% tolerance of each other — a small, real gain for boxier
# vehicles, not the fix for "boxy cars look small on the platform". That needs
# each vehicle's own proportions, not one shared constant; see the discussion
# with the user before changing this further.
REFERENCE_VEHICLE_ASPECT = 3.14

# How far past the preset's own width budget a height-normalised vehicle may
# run before the old fill-the-box scaling is used instead. A long ute, a car
# with a bike rack, or a generously cropped side-on shot sits a little wider
# than the reference car and should not be shrunk for it; something half as
# wide again is not a passenger car in a normal shot, and the old rule handles
# it more gracefully than a fixed height would.
MAX_WIDTH_OVERRUN = 1.12

# Nothing may be scaled to touch the frame edge, whatever the preset asks for.
MAX_CANVAS_FILL = 0.96

# How much of the space above the floor line a vehicle may fill. A vehicle
# taller than the ground line has nowhere to stand — its roof would render
# above the top of the canvas — which is exactly what a low, custom
# ground_y_ratio on an otherwise unmeasured dealer backdrop can trigger: the
# preset's height budget was sized for a ground line near the bottom of the
# frame, and nothing previously stopped it being applied against one near the
# middle. Kept just under 1 so a fitted vehicle still shows a sliver of the
# scene above it rather than touching the frame edge.
GROUND_LINE_HEADROOM = 0.94

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
    # Multiplies the fitted backdrop's RGB before the vehicle is placed on it.
    # 1.0 leaves the backdrop exactly as shipped. Below 1.0 dims it — this is
    # deliberately a flat multiplier rather than a curve or gamma change: the
    # complaint it answers ("the studio looks blown out") is about overall
    # brightness, not contrast, and a flat multiplier is the one adjustment
    # that reads the same from every angle, since it never depends on where
    # the vehicle or the camera is. Applied before `match_colour` samples the
    # backdrop, so the vehicle's own tone gets pulled toward the dimmed scene
    # rather than the original bright one. A dealer's own uploaded backdrop
    # (DEALER_BACKDROP) is left at 1.0: we have not measured it and darkening
    # a photo we don't understand the lighting of is more likely to look wrong
    # than right.
    backdrop_exposure: float = 1.0


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
    # Raised from the platform's own original budget (0.86/0.54) after dealer
    # feedback that the car looked small on the platform. width_ratio is the
    # one that actually matters here: for this preset the vehicle is always
    # width-bound (see REFERENCE_VEHICLE_ASPECT in _fit_vehicle), so it alone
    # sets how tall a normalised car renders. It is capped at 0.90 rather than
    # pushed further, because MAX_WIDTH_OVERRUN needs headroom above it for a
    # real silhouette (mirrors and wheel arches run nearer 3.6:1 than the 3.2
    # reference) to still clear the platform's own measured edge without
    # falling back to the older, inconsistent fill-the-box sizing.
    # vehicle_height_ratio stays out ahead of the width-driven target height so
    # it is not what's binding, but is nudged up too against the day a taller
    # backdrop or a narrower platform measurement puts it back in play.
    vehicle_width_ratio=0.90,
    vehicle_height_ratio=0.58,
    # The only surface in the asset set we have measured and can see is
    # polished. Kept well under half strength: the platform top is mid-grey
    # concrete, not glass, and an over-bright mirror image reads as a second
    # car rather than as a reflection.
    reflection_strength=0.30,
    output_size=(1280, 960),
    # Dealer feedback: the studio's white cyc wall and floor read as blown
    # out, especially on light-coloured cars. -15% is enough to take the
    # glare off without the scene reading as "dim" rather than "clean" —
    # see test_studio_backdrop_is_dimmer_than_the_source_asset.
    backdrop_exposure=0.85,
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
    # Same wall/lighting asset family as STUDIO_FULL — see its comment.
    backdrop_exposure=0.85,
)

STUDIO_PRESETS: dict[str, BackdropPreset] = {
    STUDIO_FULL.key: STUDIO_FULL,
    STUDIO_CLOSEUP.key: STUDIO_CLOSEUP,
}

# What a dealership's own backdrop gets. No measured platform, so shadows are
# not clipped and the vehicle stands on a nominal ground line.
#
# Raised from the dataclass defaults (0.72 / 0.60) after dealer feedback that
# the car looked small against their own backdrop photos. Kept short of the
# bigger bump tried briefly for this preset (0.85 / 0.72, pushed to the
# MAX_CANVAS_FILL ceiling): without a measured platform this preset has no
# idea how wide whatever is actually drawn behind the vehicle is, so pushing
# it that close to the frame edge looked neat on a backdrop shaped like the
# AutoPivot Studio's own wide floor and would not on a narrower one. See
# `match_studio_backdrop` below for backdrops where the platform *is* known —
# those get sized against its measured edge instead of this flat budget.
DEALER_BACKDROP = BackdropPreset(
    key="custom",
    label="Dealership backdrop",
    vehicle_width_ratio=0.80,
    vehicle_height_ratio=0.68,
)


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


# ── Recognising a dealer's backdrop as one of the built-in scenes ─────────────
#
# There is no shipped default backdrop set (see api/routes_backdrops.py) — a
# dealership starts empty and uploads its own photographs. But nothing stops
# someone grabbing one of the bundled studio assets and uploading it as their
# own backdrop, which is exactly what a demo listing tends to do, and when
# that happens the platform's edges genuinely are known (STUDIO_FULL and
# STUDIO_CLOSEUP measured them), even though the upload arrives through the
# generic dealer-backdrop path with no record of which stock image it came
# from. Recognising the pixels themselves closes that gap: a dealer backdrop
# that IS one of these scenes gets sized against the platform's real edge
# instead of DEALER_BACKDROP's flat, platform-blind budget.
#
# An exact byte match only catches an unmodified re-upload. A photograph
# re-saved by a browser, resized on upload, or re-encoded as a JPEG is a
# different file but the same picture, so this compares a coarse fingerprint
# of the image content instead: shrink to 8x8 greyscale and record which
# cells sit above the image's own mean brightness. Resizing and re-compression
# barely move that; a genuinely different photograph does.
_PHASH_SIZE = 8
_PHASH_MATCH_THRESHOLD = 6  # of 64 bits — see test_studio_backdrop_recognition


def _phash(image: Image.Image) -> int:
    grey = image.convert("L").resize((_PHASH_SIZE, _PHASH_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(grey, dtype=np.float64)
    bits = pixels > pixels.mean()
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _studio_asset_hashes() -> dict[str, int]:
    hashes: dict[str, int] = {}
    for key, preset in STUDIO_PRESETS.items():
        loaded = load_studio_backdrop(key)
        if loaded is not None:
            hashes[key] = _phash(loaded[0])
    return hashes


# Computed once, from whatever the bundled assets actually are, rather than
# hand-typed — so it never drifts from the files load_studio_backdrop serves.
_STUDIO_ASSET_HASHES: dict[str, int] = _studio_asset_hashes()


def match_studio_backdrop(background: Image.Image) -> BackdropPreset | None:
    """
    The measured studio preset this background is a copy of, or None.

    Sized geometry (platform_box, vehicle_width_ratio) is only trustworthy
    when the backdrop actually is the scene it was measured against — using
    it against an unrelated photograph would clamp the vehicle to an edge
    that is not really there. This is the guard: only a close fingerprint
    match returns a preset, and anything else falls through to the generic
    DEALER_BACKDROP path unchanged.
    """
    if not _STUDIO_ASSET_HASHES:
        return None
    candidate = _phash(background)
    best_key, best_distance = None, _PHASH_MATCH_THRESHOLD + 1
    for key, reference in _STUDIO_ASSET_HASHES.items():
        distance = _hamming(candidate, reference)
        if distance < best_distance:
            best_key, best_distance = key, distance
    if best_key is None or best_distance > _PHASH_MATCH_THRESHOLD:
        return None
    return STUDIO_PRESETS[best_key]


# ── Mask cleanup ───────────────────────────────────────────────────────────────

# The alpha level a pixel must clear to count as "confidently the vehicle"
# when deciding which object a blob belongs to — see _keep_largest_component.
# Not the same threshold the function keeps pixels down to afterwards (16,
# effectively "not background"): that one is fine for saying where the kept
# object's own soft edge ends, but it is far too low to decide what counts
# as a *bridge* between two objects. A shadow pooling under a dark part of
# the car — a diffuser, an exhaust surround — is exactly the kind of
# low-to-moderate, but non-zero and spatially continuous, alpha a
# segmentation model produces, and it can connect a genuinely separate blob
# (a reflection, a shadow the model mis-read as solid) to the vehicle's own
# silhouette at anywhere from 20 to 90-odd alpha without ever being
# obviously "car" at any single pixel along the way. Reproduced against a
# real photograph: a disconnected reddish disc sat a visible gap below a
# rear bumper, joined to it only by the dark, low-confidence shadow under
# the diffuser mesh — connected enough at the old threshold to count as one
# object, so it survived as a floating blob in the finished photo, and
# because `_contact_y` grounds to whichever solid pixel sits deepest with no
# way to tell "attached to the car" from "just solid", the same blob also
# dragged the whole vehicle's ground placement down to it, floating the
# actual tyres clear of the platform by the gap between them — a
# considerably worse failure than the cosmetic blob alone. Demanding genuine
# confidence to count as a bridge, while still using the old, low threshold
# for which pixels ride along with whichever object wins, keeps a real
# wing mirror or aerial (solid, not a faint shadow) intact while finally
# treating a shadow-bridged blob as the separate object it is.
_KEEP_COMPONENT_BRIDGE_ALPHA = 128


def _keep_largest_component(alpha: np.ndarray) -> np.ndarray:
    """
    Zero out every part of the mask except its single largest connected blob.

    A background-removal model scores each pixel's own foreground-ness;
    nothing in that stops it keeping a second solid object in the same
    crop just as confidently as the vehicle itself — a neighbouring car's
    fender, a bollard, a parking sign, a curb marking. `_crop_with_padding`'s
    own padding around the detected box is exactly what lets a slice of
    whatever is standing next to the car into the frame in the first place.
    Nothing downstream can tell that blob apart from the vehicle —
    `trim_transparent` crops to the union of everything non-transparent, and
    the compositor pastes whatever it is handed — so it used to ride along
    into the finished photo as a pale patch standing on its own beside the
    car, at roughly ground level since that is where a neighbouring vehicle
    or fixture would actually be.

    The vehicle is reliably the largest solid object inside its own
    detection crop; anything else that survived segmentation on its own is
    not. Which pixels count as *touching* is decided at
    `_KEEP_COMPONENT_BRIDGE_ALPHA` — confident enough that a faint shadow
    cannot masquerade as the join between two genuinely separate objects —
    run after MORPH_CLOSE has already merged small pinholes and gaps in the
    real silhouette, so a genuine part of the car narrowly connected to the
    rest (a mirror on a thin stalk, an aerial) is not mistaken for a second
    object as long as that connection is itself solid. Once the largest
    object is chosen, every pixel above the original, much lower 16 rides
    along with it — the few pixels of dilation on the kept blob below give
    that boundary a little more slack still, and let the mask's own soft
    edge survive at the boundary rather than being clipped flush to a hard
    binary cut.
    """
    bridge = (alpha > _KEEP_COMPONENT_BRIDGE_ALPHA).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bridge, connectivity=8)
    if count <= 2:
        # Label 0 is the background; at most one confidently-solid blob
        # already — nothing to separate it from.
        return alpha
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    keep = (labels == largest_label).astype(np.uint8) * 255
    keep = cv2.dilate(keep, np.ones((5, 5), dtype=np.uint8))
    # The dilation above only needs to recover the soft, lower-confidence
    # edge immediately around the winning object — not reach all the way
    # back out to the low `> 16` boundary everywhere, which would let a
    # low-alpha bridge back in exactly where it was just cut. Intersecting
    # with the original "not background" mask keeps that edge without
    # undoing the separation.
    not_background = (alpha > 16).astype(np.uint8) * 255
    keep = cv2.bitwise_and(keep, not_background)
    return np.where(keep > 0, alpha, 0).astype(np.uint8)


def refine_alpha_mask(mask: Image.Image) -> Image.Image:
    """
    Tidy a segmentation mask: close pinholes, drop anything that is not the
    vehicle, pull the edge in, feather it.

    The erode is what removes the light fringe of background that the model
    leaves around the silhouette — visible as a halo once the vehicle sits on a
    darker scene. Kept to one pixel: more starts eating wing mirrors and aerials.
    """
    alpha = np.array(mask.convert("L"), dtype=np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    alpha = _keep_largest_component(alpha)
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




# ── Levelling ──────────────────────────────────────────────────────────────────

# A quarter-angle photograph's near wheel is both bigger and lower in the
# frame than its far wheel — camera perspective, not a car that leans. That
# line was true the first time it was written and it is the reason
# `_level_vehicle` exists — but a rotation cannot tell "the near wheel sits
# lower because of perspective" apart from "the near wheel sits lower because
# the phone was held crooked", and on a real quarter-angle photograph it is
# almost always the former. Rotating the whole cutout to force both wheels
# level then does the wrong thing: it takes a car that was photographed
# correctly and rotates its entire body — bonnet, roofline, doors, all of it
# — into a bank that was never there, which reads as the car tipping over on
# the platform. That is worse than the nose-planted/tail-lifted look it was
# built to fix, not better, which is exactly what turned up the first time it
# ran against a real three-quarter photograph rather than a synthetic test
# fixture.
#
# There is no rotation that fixes this correctly for a quarter shot — that
# needs the ground line itself to recede in perspective, which is a
# considerably bigger change than this function can safely make. What this
# function CAN do safely is restrict itself to the shots where a wheel-height
# gap is not explained by perspective in the first place: front, rear and
# side. On those, both wheels sit at essentially the same distance from the
# camera, so a gap between them really does mean the photo was shot at a
# slight roll, and levelling it is the correct fix rather than a guess.
# Anything else — a quarter angle, or an angle the classifier did not return
# — is left untouched.
_LEVELLING_SAFE_ANGLES = frozenset({"front", "rear", "side"})

# Bounds how large a detected tilt is trusted before it is applied. A real
# photograph is shot close enough to level that a correction bigger than this
# almost always means the wheel search below locked onto the wrong two
# circles, not that the car genuinely needs straightening by that much.
MAX_LEVEL_CORRECTION_DEGREES = 9.0

# How sure the angle classifier has to be before its label is trusted enough
# to physically rotate the photograph, as opposed to merely being trusted as
# metadata next to it. classification.py deliberately uses a low bar
# (CLIP_ANGLE_CONFIDENCE, 0.35) for the label itself, on the reasoning that a
# wrong angle *word* beside a correct picture is low stakes and adjacent
# angles genuinely resemble each other — most of all "rear" vs. "rear_quarter"
# and "front" vs. "front_quarter", exactly the pairs either side of the safe/
# unsafe line above. Levelling is not low stakes: reproduced against a
# synthetic quarter-angle shot mislabelled "rear" at a passing-but-unconfident
# score, it rotated the cutout by several degrees and shifted the rendered
# silhouette by dozens of pixels — a car that was never tilted rendered
# banking off the platform, the "about to fly away" look reported against a
# real photograph. A label that only just cleared the metadata bar is exactly
# the label most likely to be the adjacent quarter angle in disguise, so
# levelling asks for more conviction than merely being shown. Callers that
# don't know the confidence (or the angle came from somewhere other than the
# classifier) pass None, which keeps the old behaviour of trusting the label
# alone — this is an additional gate, not a replacement for one.
LEVELLING_MIN_CONFIDENCE = 0.55

# How much of the cutout's own height, from the bottom, wheels are searched
# in. Restricting the search keeps the circle finder off the bodywork, glass
# and mirrors, which is where most of its false positives come from.
_WHEEL_SEARCH_BAND = 0.42


def _wheel_contacts(vehicle: Image.Image) -> list[tuple[float, float, float]]:
    """
    Circles found in the lower part of the vehicle's own silhouette that
    plausibly are wheels: (x, y, radius) of each, in the cutout's own pixel
    coordinates.

    This is a shape search, not a trained detector — it looks for tyres the
    way they actually render: dark, roughly circular, low in the frame. It
    can miss a wheel that is barely visible, or occasionally lock onto
    something that is not one; `_level_vehicle` is what bounds the damage
    a bad match here can do.
    """
    left, top, right, bottom = _visible_bounds(vehicle)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return []

    # Flattened onto a mid-grey so the transparent margin has *some* colour
    # to contrast against — a cutout's fully-transparent pixels can carry any
    # RGB underneath, and a dark one sitting next to an equally dark tyre
    # would otherwise erase the edge the circle search looks for.
    flat = Image.new("RGB", vehicle.size, (160, 160, 160))
    flat.paste(vehicle, (0, 0), vehicle.getchannel("A"))
    blurred = cv2.GaussianBlur(np.array(flat.convert("L"), dtype=np.uint8), (5, 5), 0)

    min_radius = max(4, round(height * 0.07))
    max_radius = max(min_radius + 2, round(height * 0.28))
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(min_radius * 1.5, 12),
        param1=80,
        param2=28,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return []

    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    band_top = top + round(height * (1 - _WHEEL_SEARCH_BAND))
    found: list[tuple[float, float, float]] = []
    for cx, cy, radius in circles[0]:
        if not (left <= cx <= right and band_top <= cy <= bottom + radius * 0.3):
            continue
        xi, yi = int(round(cx)), int(round(cy))
        if not (0 <= yi < alpha.shape[0] and 0 <= xi < alpha.shape[1]):
            continue
        if alpha[yi, xi] < 96:
            # The circle's own centre has to land on the vehicle, not on
            # background that happened to fall inside its bounding box.
            continue
        found.append((float(cx), float(cy), float(radius)))
    return found


def _level_vehicle(
    cutout: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> tuple[Image.Image, float | None]:
    """
    Rotate a vehicle cutout so its two outermost wheels sit level.

    Finds wheels as circles (see `_wheel_contacts`), takes the leftmost and
    rightmost as the front-to-rear pair, and rotates the whole cutout by the
    angle between their ground contacts. Declines to act — returning the
    cutout unchanged — whenever the shot angle is not one of
    `_LEVELLING_SAFE_ANGLES`, whenever it is one of those but the classifier
    was not confident enough for that label to be trusted with a physical
    rotation (see `LEVELLING_MIN_CONFIDENCE`), or whenever the detection looks
    unreliable: fewer than two wheels found, two candidates too close together
    to plausibly be different wheels, or a correction beyond
    `MAX_LEVEL_CORRECTION_DEGREES`. Doing nothing is always the safe fallback
    here, since this runs before the existing ground-line placement, which
    still works exactly as it did for any cutout this declines to touch.

    `angle_confidence` is optional and defaults to None, which skips the
    confidence check and keeps the old behaviour of trusting the label alone
    — for callers that don't have a confidence to offer, not for treating an
    unconfident label as if it were a confident one.

    Returns the (possibly rotated) cutout and the angle applied, or None when
    nothing was — kept in the job record so an odd result can be traced back
    to whether this fired rather than guessed at.
    """
    if angle not in _LEVELLING_SAFE_ANGLES:
        return cutout, None
    if angle_confidence is not None and angle_confidence < LEVELLING_MIN_CONFIDENCE:
        return cutout, None

    contacts = _wheel_contacts(cutout)
    if len(contacts) < 2:
        return cutout, None

    contacts.sort(key=lambda c: c[0])
    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[-1]
    if x2 - x1 < cutout.width * 0.15:
        # Two detections this close together are more likely the same wheel
        # matched twice than a genuine front-and-rear pair.
        return cutout, None

    angle = math.degrees(math.atan2((y2 + r2) - (y1 + r1), x2 - x1))
    if abs(angle) < 0.5 or abs(angle) > MAX_LEVEL_CORRECTION_DEGREES:
        return cutout, None

    logger.debug("Levelling vehicle by %.2f degrees", angle)
    levelled = cutout.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0)
    )
    return levelled, angle


# ── Quarter-angle ground recession ──────────────────────────────────────────────
#
# The floating this leaves behind on a quarter-angle photograph is not a
# levelling problem — see `_level_vehicle`'s own module comment, which
# excludes quarter angles for exactly the reason repeated here: a near wheel
# genuinely is both bigger and lower in frame than a far one on a real
# three-quarter shot, camera perspective on a car sitting perfectly flat, and
# no rotation reconciles that without banking the whole body. What a rotation
# gets wrong, though, a single rigid vertical placement gets wrong too, in the
# opposite direction: `_contact_y` grounds the whole cutout to whichever wheel
# sits deepest — the near one — and the far wheel, sitting exactly where the
# photograph always had it relative to the near one, floats clear of the
# platform by the gap between them. Levelling declines to touch that gap on
# purpose; this is what closes most of it instead, without levelling's own
# failure mode.
#
# The fix is a warp, not a rotation: nudge only the lower band of the cutout
# — the wheels and rockers, where the gap actually lives — down on the far
# side, tapering to nothing at the near wheel's own x and above the wheels
# entirely, so the roofline, glass and doors that a rotation would have
# banked are never touched. A partial correction, not a full one: closing
# every pixel of the gap would plant the far wheel at exactly the near
# wheel's own depth, which is not what a real three-quarter photograph looks
# like either — the two wheels are genuinely not the same distance from the
# camera, so some residual difference is correct, not a bug.
_QUARTER_RECEDE_SAFE_ANGLES = frozenset({"front_quarter", "rear_quarter"})

# How much of the measured near/far gap to close. Not 1.0 — see above.
_QUARTER_RECEDE_CORRECTION_FRACTION = 0.72

# How far above the far wheel's own top edge the vertical taper starts,
# in units of that wheel's own radius. The taper must reach its full 1.0
# strictly before the wheel's top — not partway down its body — so the
# wheel is translated as a rigid disc rather than sheared into an oval by
# different rows of it receiving different amounts of shift. A generic
# fraction of the vehicle's overall height was tried first and rejected:
# it put the ramp's midpoint inside the wheel itself, so the measured
# "after" contact barely moved even though pixels were genuinely
# shifting, because Hough circle detection kept latching onto the
# still-round, barely-touched upper arc of the sheared shape instead of
# the distorted whole. Anchoring to the wheel's own geometry keeps the
# wheel — and everything below its top edge, wheel arch included — moving
# together as one rigid block, with only the transition strip above it
# (fender/rocker panel) doing the smooth 0→1 ramp.
_QUARTER_RECEDE_TRANSITION_FRACTION = 0.6

# A gap bigger than this fraction of the vehicle's own height is more likely
# a bad circle match than a real photograph — the same reasoning
# `_CONTACT_WHEEL_CAP_MAX_FRACTION` applies on front/rear/side.
_QUARTER_RECEDE_MAX_FRACTION = 0.40

# Below this, the two wheels are close enough to level already that warping
# anything would only add noise.
_QUARTER_RECEDE_MIN_GAP_PX = 3.0


def _recede_quarter_ground(
    cutout: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> tuple[Image.Image, float | None]:
    """
    Partially close a quarter-angle photograph's near/far wheel gap by
    warping only the lower band of the cutout, rather than rotating it.

    Declines — returning the cutout unchanged — whenever `angle` is not one
    of `_QUARTER_RECEDE_SAFE_ANGLES`, whenever the classifier was not
    confident enough for that label to be trusted with a physical warp (the
    same `LEVELLING_MIN_CONFIDENCE` bar `_level_vehicle` uses, and for the
    same reason: an unconfident quarter label is exactly the label most
    likely to actually be a front/rear/side shot in disguise, which this
    function must not touch), whenever fewer than two wheels are found or
    they are too close together to plausibly be different wheels, whenever
    the gap between them is negligible, or whenever it is implausibly large
    for the vehicle's own height.

    Returns the (possibly warped) cutout and the number of pixels closed, or
    None when nothing was — kept in the job record the same way
    `_level_vehicle`'s own angle is, so an odd result can be traced back to
    whether this fired.
    """
    if angle not in _QUARTER_RECEDE_SAFE_ANGLES:
        return cutout, None
    if angle_confidence is not None and angle_confidence < LEVELLING_MIN_CONFIDENCE:
        return cutout, None

    contacts = _wheel_contacts(cutout)
    if len(contacts) < 2:
        return cutout, None
    contacts.sort(key=lambda c: c[0])
    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[-1]
    if x2 - x1 < cutout.width * 0.15:
        return cutout, None

    c1, c2 = y1 + r1, y2 + r2
    if c1 >= c2:
        near_x, far_x, far_top, far_r = x1, x2, y2 - r2, r2
        gap = c1 - c2
    else:
        near_x, far_x, far_top, far_r = x2, x1, y1 - r1, r1
        gap = c2 - c1
    if gap < _QUARTER_RECEDE_MIN_GAP_PX:
        return cutout, None

    _, top, _, bottom = _visible_bounds(cutout)
    height = max(1, bottom - top)
    if gap > height * _QUARTER_RECEDE_MAX_FRACTION:
        return cutout, None

    correction = gap * _QUARTER_RECEDE_CORRECTION_FRACTION
    transition = max(1.0, far_r * _QUARTER_RECEDE_TRANSITION_FRACTION)
    band_top = far_top - transition
    warped = _warp_recede(cutout, near_x, far_x, correction, band_top, far_top)
    return warped, float(correction)


def _warp_recede(
    cutout: Image.Image,
    near_x: float,
    far_x: float,
    correction: float,
    band_top: float,
    full_at: float,
) -> Image.Image:
    """
    Shift the lower band of `cutout` down by up to `correction` pixels on the
    far side, tapering to zero at `near_x` and above `band_top`, reaching the
    full shift by `full_at` (the far wheel's own top edge) so that wheel and
    everything below it move as one rigid block rather than shearing. A
    per-column, per-row displacement rather than a single affine transform,
    because the taper needs to reach zero along two independent axes at once
    — flat by `near_x` so the near wheel does not move, and flat above
    `band_top` so the body does not.
    """
    alpha = np.array(cutout.getchannel("A"), dtype=np.uint8)
    rgb = np.array(cutout.convert("RGB"), dtype=np.uint8)
    h, w = alpha.shape

    pad = int(math.ceil(correction)) + 2
    padded_h = h + pad

    xs = np.arange(w, dtype=np.float32)
    if near_x == far_x:
        return cutout
    t = np.clip((xs - far_x) / (near_x - far_x), 0.0, 1.0)
    horiz_shift = correction * (1.0 - t)  # `correction` at far_x, 0 at/past near_x

    ys = np.arange(padded_h, dtype=np.float32)
    reach = max(1.0, full_at - band_top)
    vert_taper = np.clip((ys - band_top) / reach, 0.0, 1.0)  # 0 above band_top, 1 at/below full_at

    shift_grid = horiz_shift[None, :] * vert_taper[:, None]
    map_x = np.tile(xs[None, :], (padded_h, 1))
    map_y = np.tile(ys[:, None], (1, w)) - shift_grid

    remapped_alpha = cv2.remap(
        alpha, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    remapped_rgb = cv2.remap(
        rgb, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    result = Image.fromarray(remapped_rgb, mode="RGB").convert("RGBA")
    result.putalpha(Image.fromarray(remapped_alpha, mode="L"))
    return result


# ── Geometry ───────────────────────────────────────────────────────────────────

def _visible_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha > 6)
    if xs.size == 0 or ys.size == 0:
        return 0, 0, image.width, image.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# How opaque a pixel must be to count as confidently vehicle, for finding
# each column's solid ground contact before any soft-edge allowance.
_CONTACT_SOLID_ALPHA = 128

# The looser bound `_contact_y` still reaches into past the solid edge —
# close to `_visible_bounds`' own `> 6` — to pick up a genuinely soft,
# gradually-fading tyre edge rather than snapping to a hard boundary. See
# `_CONTACT_MAX_SOFT_EXTENSION` for why this alone is not the whole story.
_CONTACT_SOFT_ALPHA = 32

# How far past a column's own solid edge the soft threshold above may still
# extend the contact line. A real tyre-against-its-own-shadow fade is a few
# pixels wide (the regression test below pins reaching a 12-row one); a
# background-removal model can also retain the car's actual CAST shadow on
# the ground as faint but non-zero alpha, and that is not a few pixels — it
# can trail tens of pixels beyond the tyre in every column under the car, on
# a bright day or light pavement. Uncapped, `_contact_y` cannot tell that
# trailing shadow apart from a soft tyre edge: both are continuous low alpha
# starting right where the solid pixels end, and unlike the isolated-pixel
# case the quantile below was built to shrug off, a shadow like this touches
# nearly every column, so it is not an outlier the quantile filters out —
# it IS the distribution. Reproduced synthetically (add a faint fading skirt
# under an otherwise ordinary cutout and the contact line — and with it the
# whole vehicle — moves upward by however far the skirt reaches): a real
# dealer photograph with a visible cast shadow read as the car floating
# well clear of the platform, sometimes dramatically, which is the opposite
# direction from the under-reach `_CONTACT_SOFT_ALPHA` was lowered to fix.
# Capping the soft extension keeps the genuine-fade case working (see the
# pinned 12-row test) while refusing to let a shadow's own reach set where
# the tyre supposedly is.
_CONTACT_MAX_SOFT_EXTENSION = 15


def _contact_y(
    vehicle: Image.Image,
    angle: str | None = None,
    angle_confidence: float | None = None,
) -> int:
    """
    The line the tyres sit on.

    Deliberately not the lowest opaque pixel: a single stray row of mask —
    a shadow remnant from the original ground, a segmentation spike — would
    lift the whole car off the floor. Taking the 0.97 quantile of each
    column's own contact row ignores those without losing the real contact
    line.

    Each column's own contact row is its lowest confidently-solid pixel
    (`_CONTACT_SOLID_ALPHA`), extended downward by the looser
    `_CONTACT_SOFT_ALPHA` bound to reach a genuinely soft tyre edge — but
    capped at `_CONTACT_MAX_SOFT_EXTENSION` past the solid edge, so a
    retained cast shadow trailing much further than that cannot be mistaken
    for the tyre itself; see that constant for how this was found. A column
    with no solid pixel at all — shadow puddling out beside the car, past
    its own footprint, with nothing solid above it — contributes nothing:
    there is no vehicle there to find the ground under.

    `angle` and `angle_confidence` gate a second correction,
    `_wheel_grounded_contact_cap` — reusing exactly `_level_vehicle`'s own
    `_LEVELLING_SAFE_ANGLES`/`LEVELLING_MIN_CONFIDENCE` bar, because it rests
    on the identical assumption: a front, rear or side shot's two wheels sit
    at the same true distance from the camera, so nothing here should treat
    an unconfirmed or quarter-angle label as license to trust that. See that
    function for what the correction is and why it is needed even after
    levelling has already run.
    """
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid = alpha >= _CONTACT_SOLID_ALPHA
    soft = alpha >= _CONTACT_SOFT_ALPHA

    bottoms: list[int] = []
    for x in range(alpha.shape[1]):
        edge = _capped_soft_edge(solid[:, x], soft[:, x])
        if edge is not None:
            bottoms.append(edge)

    if not bottoms:
        return _visible_bounds(vehicle)[3]
    bottoms_arr = np.asarray(bottoms, dtype=np.float32)
    contact = int(round(float(np.quantile(bottoms_arr, 0.97))))

    # Temporary diagnostic for the job-609/611/615 "floating vehicle" report:
    # a retained floor reflection read as solid (not soft) alpha would widen
    # this spread well beyond what a genuine tyre-shadow fade produces, and
    # neither _CONTACT_MAX_SOFT_EXTENSION nor the wheel cap below guards
    # against solid alpha specifically. Logged at INFO, not DEBUG, so it
    # shows up in the console without changing the logging config, and is
    # meant to come out once real console output from a reprocessed job is
    # available — remove once the floating report is root-caused.
    naive_bottom = _visible_bounds(vehicle)[3]
    logger.info(
        "_contact_y: quantile contact=%d naive_bottom=%d spread(p50-p97)=%.0f "
        "angle=%r confidence=%r",
        contact, naive_bottom,
        contact - float(np.quantile(bottoms_arr, 0.50)),
        angle, angle_confidence,
    )

    if angle in _LEVELLING_SAFE_ANGLES and not (
        angle_confidence is not None and angle_confidence < LEVELLING_MIN_CONFIDENCE
    ):
        cap = _wheel_grounded_contact_cap(vehicle)
        if cap is not None and cap < contact:
            logger.info(
                "_contact_y: wheel cap pulled contact from %d to %d (-%d)",
                contact, cap, contact - cap,
            )
        if cap is not None:
            contact = min(contact, cap)
    return contact


# How far `_wheel_grounded_contact_cap` may pull the quantile-based contact
# row upward before its correction is distrusted as a bad circle match
# instead of a genuine reading — the same reasoning as
# `MAX_LEVEL_CORRECTION_DEGREES`, but a real correction here can be much
# bigger than a levelling one (see that function for why).
_CONTACT_WHEEL_CAP_MAX_FRACTION = 0.35


def _wheel_grounded_contact_cap(vehicle: Image.Image) -> int | None:
    """
    An upper bound on `_contact_y`'s ground-contact row, taken from the two
    outermost detected wheels (`_wheel_contacts`) rather than an alpha
    threshold.

    `_contact_y`'s per-column quantile grounds the vehicle to whichever wheel
    sits deepest in the frame — correct when both wheels genuinely touch the
    same row, but wrong whenever they don't. An ordinary side-on photograph
    shot at even a slight angle to the car's flank — not enough of an angle
    for the classifier to call it a quarter shot — puts the nearer wheel both
    bigger and lower in frame than the farther one: camera perspective, the
    same effect `_level_vehicle`'s own comment describes for quarter angles,
    just smaller. That is not a roll, so no rotation fixes it, and grounding
    the whole rigid cutout to whichever wheel sits deepest floats the other
    one clear of the platform by exactly the gap between them — confirmed
    against a real dealer photograph where the two wheels' own solid tyre
    pixels ended 92px apart in the same column-aligned image, nowhere near
    the few-pixel spread a genuine soft edge or shadow remnant leaves.

    Capping the contact row at the shallower wheel's own contact point bounds
    that float at zero: the deeper wheel sits a little into the platform
    instead, which reads as a shadow rather than a rendering fault. Returns
    None — leaving `_contact_y` exactly as it was — whenever fewer than two
    wheels are found, they are too close together to plausibly be different
    wheels, or the correction would exceed `_CONTACT_WHEEL_CAP_MAX_FRACTION`
    of the vehicle's own height, which is more likely a bad circle match than
    a real one.
    """
    contacts = _wheel_contacts(vehicle)
    if len(contacts) < 2:
        return None
    contacts.sort(key=lambda c: c[0])
    (x1, y1, r1), (x2, y2, r2) = contacts[0], contacts[-1]
    if x2 - x1 < vehicle.width * 0.15:
        return None

    _, top, _, bottom = _visible_bounds(vehicle)
    height = max(1, bottom - top)
    shallow = min(y1 + r1, y2 + r2)
    deep = max(y1 + r1, y2 + r2)
    if (deep - shallow) > height * _CONTACT_WHEEL_CAP_MAX_FRACTION:
        return None
    return int(round(shallow))


def _capped_soft_edge(has_solid: np.ndarray, has_soft: np.ndarray) -> int | None:
    """
    Shared by `_contact_y` (per column) and `_shadow_capped_bottom` (per row):
    given two 1-D boolean masks over the same slices — one confidently solid,
    one merely soft — return the deepest index that should count as the real
    edge of the object, or None when the slice has no solid content at all.

    That is the deepest solid index, extended by the soft mask up to
    `_CONTACT_MAX_SOFT_EXTENSION` further — enough for a genuinely soft,
    gradually-fading edge, not enough for a retained shadow trailing on for
    tens of pixels past it. See `_CONTACT_MAX_SOFT_EXTENSION` for why both
    callers need this rather than trusting the soft mask on its own.
    """
    solid_idx = np.flatnonzero(has_solid)
    if not solid_idx.size:
        return None
    solid_edge = int(solid_idx[-1])
    soft_idx = np.flatnonzero(has_soft)
    soft_edge = int(soft_idx[-1]) if soft_idx.size else solid_edge
    return min(soft_edge, solid_edge + _CONTACT_MAX_SOFT_EXTENSION)


def _shadow_capped_bottom(vehicle: Image.Image) -> int | None:
    """
    The vehicle's own lowest row, for sizing rather than ground placement —
    robust to the same retained-cast-shadow contamination `_contact_y`
    guards against, but row-wise rather than per-column, and without the
    quantile: `_fit_vehicle` needs one number for how tall the cutout
    genuinely is, not a ground line.

    Left uncorrected, a shadow trailing below the car inflates the cutout's
    measured height (`_visible_bounds` has no opinion on what is shadow and
    what is bodywork), and since sizing scales the whole vehicle to a target
    height divided by that measurement, a taller-than-it-should-be reading
    renders the entire car smaller — reproduced synthetically: the same
    front-on cutout rendered visibly smaller the further a faint trailing
    skirt beneath it reached, nothing about the car itself having changed.
    That is a different symptom from the floating this shares its threshold
    constants with, but the same underlying cause. Returns None when there
    is no confidently-solid row at all.
    """
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid_rows = (alpha >= _CONTACT_SOLID_ALPHA).any(axis=1)
    soft_rows = (alpha >= _CONTACT_SOFT_ALPHA).any(axis=1)
    return _capped_soft_edge(solid_rows, soft_rows)


def _shadow_capped_side(vehicle: Image.Image, *, leading: bool) -> int | None:
    """
    The vehicle's own left or right edge, for sizing rather than ground
    placement — `_shadow_capped_bottom`'s own reasoning, turned ninety
    degrees.

    A cast shadow does not only trail downward from a car: raking light
    across a side-on shot throws it out to one side along the ground, and
    background removal can retain a long, faint tail of it exactly the way
    it retains one below the car. `_fit_vehicle`'s width clamp used to read
    straight off `cutout.width`, which has no opinion on what is shadow and
    what is bodywork any more than `cutout.height` did — so a side-on shot
    with such a shadow measured as wider than the car actually is, and
    scaling against that inflated width shrank the whole vehicle to fit a
    frame the real car was never close to filling. Reproduced synthetically
    against an ordinary ~3.5:1 side-on cutout: a shadow reaching a fifth of
    the car's own length out to one side rendered it roughly a fifth
    shorter than the same cutout with no shadow at all, nothing about the
    car itself having changed — the width sibling of the front-on shrink
    `_shadow_capped_bottom`'s own docstring describes.

    `leading=True` caps the left edge (a shadow trailing off further right
    pulls `right` in from that side instead — see the other caller).
    Returns None when there is no confidently-solid column at all.
    """
    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    solid_cols = (alpha >= _CONTACT_SOLID_ALPHA).any(axis=0)
    soft_cols = (alpha >= _CONTACT_SOFT_ALPHA).any(axis=0)
    if leading:
        solid_cols, soft_cols = solid_cols[::-1], soft_cols[::-1]
    edge = _capped_soft_edge(solid_cols, soft_cols)
    if edge is None:
        return None
    return len(solid_cols) - 1 - edge if leading else edge


# How much of a detected wheel's own radius may be missing from the cutout's
# mask before this stops trying to patch it. A tyre trimmed a few pixels
# short by an uncertain segmentation edge is worth restoring; a wheel this
# far short of its detected circle is more likely a bad circle match than a
# genuine gap, and patching that would draw a tyre where there is not one.
_MAX_WHEEL_PATCH_FRACTION = 0.35


def _patch_wheel_gaps(vehicle: Image.Image) -> Image.Image:
    """
    Extend a wheel's mask up to its own detected circle where the cutout's
    alpha falls short of it.

    A tyre against its own shadow, or against a shadowed wheel arch, can lose
    real pixels to background removal — not a soft fade at the edge (see
    `_contact_y`), a confidently-missing chunk. Left alone, that one wheel
    renders visibly clear of the platform while an unaffected wheel on the
    same car touches down normally, which reads as the car resting on one
    wheel and floating on the other — reported by a dealer as "the back
    bumper is uplifted". The same circle search `_level_vehicle` uses
    recovers a wheel's true extent even from a partial arc, so wherever that
    circle reaches further down than the mask currently does, this fills the
    gap — colour sampled from the tyre's own visible pixels, the whole mask
    softened afterwards so the graft does not read as a seam.

    Declines per wheel, not for the whole cutout, whenever the missing
    fraction is larger than `_MAX_WHEEL_PATCH_FRACTION` of that wheel's own
    radius: past that point a bad circle match is more likely than a genuine
    gap, and patching one would draw a tyre where there is not one.
    """
    contacts = _wheel_contacts(vehicle)
    if not contacts:
        return vehicle

    alpha = np.array(vehicle.getchannel("A"), dtype=np.uint8)
    rgb = np.array(vehicle.convert("RGB"), dtype=np.uint8)
    height, width = alpha.shape
    patched_any = False

    for cx, cy, radius in contacts:
        cx_i, cy_i, r_i = int(round(cx)), int(round(cy)), int(round(radius))
        x0, x1 = max(0, cx_i - r_i), min(width, cx_i + r_i + 1)
        y0, y1 = max(0, cy_i - r_i), min(height, cy_i + r_i + 1)
        if x1 <= x0 or y1 <= y0 or not (0 <= cx_i < width):
            continue

        column = alpha[y0:y1, cx_i]
        opaque_rows = np.flatnonzero(column >= 32)
        visible_bottom = y0 + int(opaque_rows[-1]) if opaque_rows.size else cy_i
        missing = (cy_i + r_i) - visible_bottom
        if missing <= 0 or missing > radius * _MAX_WHEEL_PATCH_FRACTION:
            continue

        yy, xx = np.mgrid[y0:y1, x0:x1]
        disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
        window_alpha = alpha[y0:y1, x0:x1]
        opaque = window_alpha >= 32
        gap = disc & ~opaque
        if not gap.any():
            continue

        tyre_pixels = rgb[y0:y1, x0:x1][disc & opaque]
        if tyre_pixels.size == 0:
            continue
        fill_colour = np.median(tyre_pixels.reshape(-1, 3), axis=0)

        window_rgb = rgb[y0:y1, x0:x1]
        window_rgb[gap] = fill_colour
        window_alpha[gap] = 255
        patched_any = True

    if not patched_any:
        return vehicle

    result = Image.fromarray(rgb, "RGB").convert("RGBA")
    softened = cv2.GaussianBlur(alpha, (0, 0), 0.6)
    result.putalpha(Image.fromarray(softened, "L"))
    return result


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


def _apply_backdrop_exposure(canvas: Image.Image, factor: float) -> Image.Image:
    """Scale the backdrop's RGB by `factor`, alpha untouched. `factor == 1.0` is a no-op."""
    if factor == 1.0:
        return canvas
    array = np.array(canvas.convert("RGBA"), dtype=np.float32)
    array[:, :, :3] = np.clip(array[:, :, :3] * factor, 0, 255)
    return Image.fromarray(array.astype(np.uint8), mode="RGBA")


def _fit_vehicle(
    cutout: Image.Image,
    preset: BackdropPreset,
    size: tuple[int, int],
    ground_y: int | None = None,
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

    `ground_y` — the floor line's position on the canvas, when the preset
    stands the vehicle on one — additionally bounds how tall the vehicle may
    be. Every other limit here bounds the vehicle against the whole frame, but
    a vehicle is pasted with its tyres *on* the ground line, so what actually
    matters is the room between that line and the top of the canvas: a vehicle
    sized without regard for it can be told to stand on a line a third of the
    way down the frame and rendered at a height meant for a line near the
    bottom, which crops its roof off above the canvas.
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

    if ground_y is not None:
        headroom = ground_y * GROUND_LINE_HEADROOM
        max_height = min(max_height, headroom)
        limit_height = min(limit_height, headroom)

    fill_scale = min(max_width / cutout.width, max_height / cutout.height)
    scale, normalised = fill_scale, False

    left, top, right, bottom = _visible_bounds(cutout)
    # A retained cast shadow trailing below the vehicle is exactly what
    # `_contact_y` guards ground placement against; here it inflates the
    # measured height instead, shrinking the whole car to hit the same
    # target — see `_shadow_capped_bottom`. Only ever pulls `bottom` up
    # towards the vehicle's own solid extent, never pushes it further out.
    capped_bottom = _shadow_capped_bottom(cutout)
    if capped_bottom is not None:
        bottom = min(bottom, capped_bottom + 1)
    # The same shadow can trail sideways instead of down — raking light
    # across a side-on shot — and inflate the measured *width* the same
    # way; see `_shadow_capped_side`. Pulls `left`/`right` in towards the
    # vehicle's own solid extent, never pushes them further out.
    capped_left = _shadow_capped_side(cutout, leading=True)
    if capped_left is not None:
        left = max(left, capped_left)
    capped_right = _shadow_capped_side(cutout, leading=False)
    if capped_right is not None:
        right = min(right, capped_right + 1)
    visible_w, visible_h = right - left, bottom - top
    if visible_w > 0 and visible_h > 0:
        target_height = min(max_height, max_width / REFERENCE_VEHICLE_ASPECT)
        candidate = target_height / visible_h

        # Clamped to the limits rather than abandoned at them, against
        # `visible_w`/`visible_h` — the shadow-capped measurements, not
        # `cutout.width`/`cutout.height` — and that difference is not
        # cosmetic on either axis. A retained cast shadow is exactly the
        # case `capped_bottom`/`capped_left`/`capped_right` above exist to
        # neutralise for the numerator, but the raw cutout still contains
        # every pixel of that trailing shadow regardless of the cap; only
        # the local bounds used for sizing move, not the image itself. A
        # clamp built from the raw cutout dimensions reintroduces the exact
        # shrink the caps were just built to remove: a front-on shot with a
        # long, faint floor shadow measured true car height correctly for
        # `candidate`, then had that candidate strangled by
        # `limit_height / cutout.height` anyway, because the shadow was
        # still sitting in `cutout.height` even though `visible_h` no
        # longer counted it — reproduced against a real gallery, three
        # angles of the same car rendering at a consistent height and the
        # front-on shot, whose shadow pools most directly beneath it,
        # coming out visibly shorter than the rest. The width side is the
        # same failure turned ninety degrees: a side-on shot with a shadow
        # trailing out to one side measured as wider than the car actually
        # is, and clamping against `cutout.width` shrank the whole vehicle
        # to fit a frame it was never close to filling — reproduced
        # synthetically, and confirmed against a real side-on photograph
        # that rendered visibly smaller than the same car's other angles
        # with no such shadow. `visible_w`/`visible_h` are always
        # `<= cutout.width`/`cutout.height` (the caps only ever pull the
        # bounds in), so this can only loosen the clamp, never make it more
        # permissive than the uncapped version already was.
        clamped = min(
            candidate,
            limit_width / visible_w,
            limit_height / visible_h,
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


def _ground_line(preset: BackdropPreset, canvas_h: int) -> int:
    """
    The floor's y-coordinate on the canvas, independent of any particular
    vehicle — needed before a vehicle is fitted, so its height can be bounded
    by the room actually available above the line it will stand on.
    """
    ratio = (
        preset.platform_contact_y_ratio
        if preset.platform_contact_y_ratio is not None
        else preset.ground_y_ratio
    )
    return round(canvas_h * ratio)


def _vehicle_position(
    vehicle: Image.Image,
    preset: BackdropPreset,
    size: tuple[int, int],
    profile: _AngleProfile = _NEUTRAL_PROFILE,
    angle: str | None = None,
    angle_confidence: float | None = None,
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
        platform_left = canvas_w * preset.platform_box[0]
        platform_right = canvas_w * preset.platform_box[2]
        platform_centre_x = (platform_left + platform_right) / 2
        x = round(platform_centre_x - (left + right) / 2 + offset)

        # A hard backstop, the same principle `_fit_vehicle` already applies to
        # scale: the platform edge is a measured, physical limit, and a car
        # overhanging it reads as a rendering fault however it got there.
        # Centring here trusts `_visible_bounds` to be the car's own true
        # extent, but a retained shadow or floor reflection reaching further
        # past one end of the vehicle than the other — the horizontal sibling
        # of the trailing shadow `_shadow_capped_bottom` guards against
        # vertically — inflates one side of that box without the other,
        # which pulls this centring off by exactly that amount. Found on a
        # real side-on photograph: the rear end had room to spare while the
        # front hung visibly off the platform's own edge. Sliding the result
        # back inside the measured edges fixes the visible symptom
        # immediately regardless of which side the inflation came from,
        # without touching scale — only when the vehicle is narrow enough to
        # fit at all; a genuinely too-wide cutout is `_fit_vehicle`'s own
        # concern; not this function's to solve by pushing it off-centre.
        vehicle_width = right - left
        if vehicle_width <= platform_right - platform_left:
            x = max(x, round(platform_left - left))
            x = min(x, round(platform_right - right))
    else:
        x = round(canvas_w / 2 - (left + right) / 2 + offset)

    if preset.placement == "center":
        y = round(canvas_h * 0.52 - (top + bottom) / 2)
        return int(x), int(y), min(canvas_h - 1, int(y + bottom))

    contact = (
        _contact_y(vehicle, angle, angle_confidence) if preset.platform_box else bottom
    )
    ground_y = _ground_line(preset, canvas_h)
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

    Blur is a fraction of the vehicle's own pixel height rather than a fixed
    number of pixels, for the same reason every other measurement here is a
    ratio of the vehicle: STUDIO_FULL's own vehicle_width_ratio was raised
    after this shipped so the car renders bigger on the platform, and a fixed
    pixel blur does not grow with it — the shadow's edge gets relatively
    harder, not softer, exactly as the car it belongs to gets bigger. 0.045
    and 0.0225 reproduce the blur the fixed 24px/12px gave at the vehicle size
    this was tuned against, and now hold that same softness at any size.
    """
    height = max(1, alpha.height)
    return [
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.14, max(8.0, height * 0.045), 0.14 * profile.shadow_depth, 1.04 * profile.shadow_width,
        ),
        _build_shadow(
            alpha, vehicle_x, ground_y,
            0.32, max(4.0, height * 0.0225), 0.075 * profile.shadow_depth, 0.90 * profile.shadow_width,
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


def _ambient_patch(backdrop: Image.Image) -> np.ndarray:
    """
    A sample of the scene's own ambient light — its wall and ceiling — rather
    than the region immediately behind where the vehicle will stand.

    For a "ground" placement that region is mostly the platform or floor
    itself: a vehicle sized to the platform has its own bounding box sitting
    low in the frame, largely over the floor rather than the wall behind it.
    Matching a car's tone to that reading pulls it towards the floor's own
    colour — usually darker than the room around it — rather than towards
    the wall and ceiling lighting a viewer actually reads as "how bright is
    this room", which is backwards: it makes a car placed in a bright studio
    look duller than the room it is standing in, not better matched to it.
    The top slice of the canvas is wall and ceiling in every studio scene
    this ships with, and in the ordinary run of a dealer's own upload too.
    """
    band_bottom = max(1, round(backdrop.height * 0.35))
    return np.array(
        backdrop.crop((0, 0, backdrop.width, band_bottom)).convert("RGB"),
        dtype=np.uint8,
    )


# How far a vehicle's own lightness spread is pulled towards the backdrop
# patch's before the existing mean-shift runs. A source photo shot in flat,
# overcast daylight and a studio lit for photography sit at genuinely
# different contrast levels — matching only the average tone still leaves a
# flat car looking pasted onto a punchier scene, and vice versa. Kept small
# and, unlike the mean-shift below, kept off a solid-colour cutout (nothing to
# scale a spread of zero towards).
CONTRAST_MATCH_STRENGTH = 0.6
CONTRAST_MATCH_CLAMP = 0.18


def match_colour(
    vehicle: Image.Image, backdrop: Image.Image, x: int, y: int,
    *, placement: str = "center",
) -> Image.Image:
    """
    Nudge the vehicle towards the scene's lighting. Weak and clamped on purpose.

    Lightness moves at 12% of the difference and no more than 18 LAB units;
    the colour axes at 15% and no more than 5. A dealer's photograph has to
    stay the colour the car actually is, so this corrects for the light it was
    shot under and stops well short of repainting it. Contrast — how spread
    out the vehicle's own lightness values are — is pulled a little towards
    the backdrop's separately: two photos can share a mean tone and still read
    as lit completely differently.

    `placement` picks where "the scene's lighting" is read from. "ground"
    uses `_ambient_patch` — the wall and ceiling — because the region right
    behind a standing vehicle is mostly the floor or platform it stands on,
    and a dark floor is not what a viewer reads as how bright the room is.
    Anything else keeps the original local patch immediately behind the
    vehicle, which is correct for a close-up composed against a wall with no
    floor to skew it.
    """
    rgba = np.array(vehicle.convert("RGBA"), dtype=np.uint8)
    opaque = rgba[:, :, 3] > 24
    patch = (
        _ambient_patch(backdrop) if placement == "ground"
        else _backdrop_patch(backdrop, x, y, vehicle.width, vehicle.height)
    )
    if not np.any(opaque) or patch.size == 0:
        return vehicle

    vehicle_lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    backdrop_lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    vehicle_mean = vehicle_lab[opaque].mean(axis=0)
    backdrop_mean = backdrop_lab.reshape(-1, 3).mean(axis=0)

    vehicle_lightness_std = float(vehicle_lab[opaque][:, 0].std())
    if vehicle_lightness_std > 1.0:
        backdrop_lightness_std = float(backdrop_lab[:, :, 0].std())
        relative_gap = (backdrop_lightness_std - vehicle_lightness_std) / vehicle_lightness_std
        contrast_scale = 1.0 + np.clip(
            relative_gap, -CONTRAST_MATCH_CLAMP, CONTRAST_MATCH_CLAMP
        ) * CONTRAST_MATCH_STRENGTH
        vehicle_lab[:, :, 0] = (
            vehicle_mean[0] + (vehicle_lab[:, :, 0] - vehicle_mean[0]) * contrast_scale
        )

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
    angle_confidence: float | None = None,
) -> tuple[Image.Image, dict]:
    """
    Place a cut-out vehicle onto a backdrop.

    Returns the finished image and what was done to it, for the job record.
    The cutout is expected to have had its plates treated already: it is
    rescaled here, so any coordinates taken from it beforehand stop being valid.

    `angle` is the shot angle, if something upstream knows it. It refines
    horizontal placement and the shape of the shadow pool, and it gates
    wheel-levelling (see `_LEVELLING_SAFE_ANGLES`): passing nothing, or a
    label this module does not recognise, composes exactly as it would have
    without the argument — which for levelling means it is left off, the same
    as an unsafe angle. It is keyword-only so that the two- and three-
    positional-argument calls that already exist keep working untouched.

    `angle_confidence` is the classifier's own confidence in `angle`, if
    known (see `LEVELLING_MIN_CONFIDENCE`). Leaving it out trusts `angle`
    alone, the same as before this parameter existed; it exists because a
    label that only just cleared the classifier's own low bar for showing it
    as metadata is exactly the label most likely to be an adjacent angle in
    disguise — "rear_quarter" read as "rear" — and physically rotating a
    photograph on that little confidence is a worse failure than not
    levelling a car that genuinely needed it.
    """
    cutout = trim_transparent(cutout.convert("RGBA"))
    levelled, level_angle = _level_vehicle(cutout, angle, angle_confidence)
    cutout = trim_transparent(levelled)
    receded, recede_px = _recede_quarter_ground(cutout, angle, angle_confidence)
    cutout = trim_transparent(receded)
    cutout = _patch_wheel_gaps(cutout)
    size = _canvas_size(backdrop, preset)
    canvas = _fit_backdrop(backdrop, size)
    canvas = _apply_backdrop_exposure(canvas, preset.backdrop_exposure)
    profile = _angle_profile(angle)

    ground_hint = _ground_line(preset, size[1]) if preset.placement == "ground" else None
    vehicle, normalised = _fit_vehicle(cutout, preset, size, ground_y=ground_hint)
    x, y, ground_y = _vehicle_position(vehicle, preset, size, profile, angle, angle_confidence)
    vehicle = match_colour(vehicle, canvas, x, y, placement=preset.placement)

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
        "levelled_degrees": level_angle,
        "quarter_ground_correction_px": recede_px,
    }
