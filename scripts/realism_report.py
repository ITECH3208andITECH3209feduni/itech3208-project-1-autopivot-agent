"""Record what a realism change actually did, as numbers and as pictures.

REALISM_PLAN.md closes by asking that the before and the after of every phase be
recorded as it lands, "far more convincing than an assertion that the output
looks better". This is where that recording happens. Point it at a folder of
cut-out vehicles and it composites every one of them, writes the renders where a
person can look at them side by side, measures everything metrics.py can
measure, asks elevation.py where the camera was, and writes the lot out as a
metrics file and a short summary.

    python -m scripts.realism_report --synthetic --label 'harness smoke test'
    python -m scripts.realism_report --cutouts ~/cutouts --label 'before phase 1'
    python -m scripts.realism_report --cutouts ~/cutouts --label 'after phase 1' \
        --out evidence/after --baseline evidence/metrics.json

The third form is the one that matters. A phase is judged as a delta against a
metrics file saved before it started, not as an absolute: nobody reading the
report knows whether an edge-quality ratio of 0.27 is good, and everybody can
see that it used to be 0.11.

INPUTS, AND WHY THE HARNESS INSISTS ON SAYING WHERE THEY CAME FROM.

The repository contains no real cut-outs — they are dealer photographs — so
`--synthetic` draws its own. A synthetic run proves this harness works end to
end. It proves nothing whatever about realism, because the vehicles in it were
drawn by the same repository that is being measured. Every synthetic run is
therefore labelled as one, in the metrics file and at the top of the summary, and
the label survives a cut-out being copied out of the smoke-run directory without
its sidecar because it is also written into the PNG itself. A technical report
quoting these figures as evidence that a composite looks better would be
dishonest, and this labelling is what stops it happening by accident.

Nothing here needs a GPU, a model, a database or a network: only the standard
library, cv2, numpy, PIL and the three pure modules. That is deliberate. A
measurement nobody else can reproduce on their own laptop is not evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

import compositing
import elevation
import metrics

ROOT = Path(__file__).resolve().parent.parent

# Renders are large binaries and the metrics file is small, so .gitignore keeps
# the second and drops the first. Defaulting to a path under the repository
# rather than to the working directory is what makes that hold wherever the
# script is run from.
DEFAULT_OUTPUT_DIR = ROOT / "evidence"

# Stamped into every metrics file. A later stage comparing against a baseline
# needs to know it is reading the same shape of file, and "the keys I expected
# are missing" is a far worse thing to work out from a traceback than a version
# that does not match.
SCHEMA = "autopivot.realism-report/1"

# Written into the PNG of every cut-out this script draws. A sidecar can be lost
# by copying the image somewhere else; a text chunk travels inside the file, and
# a synthetic vehicle silently reported as a photograph is the one failure this
# harness exists to prevent.
SYNTHETIC_PNG_KEY = "autopivot-synthetic"

CUTOUT_SUFFIXES = (".png", ".webp")

# Taken from the module that owns the vocabulary rather than typed out again
# here, so that an angle added there does not leave this script rejecting it.
# Only used to warn: both compositing.py and elevation.py degrade gracefully on
# a label they do not recognise, so an unknown angle costs accuracy rather than
# failing the run, and a typo in a sidecar would otherwise be invisible.
KNOWN_ANGLES = tuple(elevation.ANGLE_ELEVATION_PRIOR_DEG)

# The rungs of elevation.py's cascade that measured something, as against the
# two that fall back on how dealers are known to shoot. Pooling the two kinds
# together without saying which is which would let a population prior be quoted
# as an observation. Taken from the module that owns the cascade rather than
# repeated here: the compositor gates horizon alignment on the same distinction,
# and two copies of it would eventually disagree about which is which.
MEASURED_ELEVATION_METHODS = elevation.MEASURED_METHODS


# ── The synthetic vehicles ─────────────────────────────────────────────────────

# Big enough that a wheel clears elevation.WHEEL_MIN_MAJOR_PX: a 0.632 m wheel at
# 400 px/m is 253 px across, which is roughly what a car filling a 3000 px
# photograph gives and is the regime that module says it needs.
SYNTHETIC_PIXELS_PER_METRE = 400

# Saturated paint against near-neutral rubber, which is the discrimination
# elevation.TYRE_SATURATION_MAX and TYRE_LIGHTNESS_CEILING are drawn to make. A
# body colour that happened to be dark and grey would leave the wheel rung
# segmenting the whole car as one tyre, and the smoke run would then exercise
# nothing.
SYNTHETIC_BODY_COLOUR = (176, 62, 58)
SYNTHETIC_TYRE_COLOUR = (28, 28, 30)

# A 16-inch rim inside the tyre, drawn light. Not decoration: elevation.py takes
# its darkness threshold from the 15th percentile of the search band, so a wheel
# that is dark all the way through pushes that percentile down into the rubber
# itself and the threshold then selects nothing at all. Drawn without a rim the
# whole set fell through to the shot-angle prior, and the smoke run exercised
# none of the machinery it exists to exercise.
SYNTHETIC_RIM_COLOUR = (185, 185, 190)
SYNTHETIC_RIM_RADIUS_M = 0.2032

# The wheel arch, reproduced as the thing that actually happens in a photograph:
# body paint over the top of the tyre. elevation._chord_ratio exists because of
# it, so a synthetic set without it would exercise the easy case only.
SYNTHETIC_ARCH_CLIP = 0.15

# A soft edge, because a segmentation mask has one and a drawn shape does not.
# Without it every synthetic cut-out scores exactly zero for edge quality, which
# is a true number about a fixture rather than a smoke test of the measure.
SYNTHETIC_EDGE_SOFTNESS_PX = 1.4

SYNTHETIC_WHEELBASE_M = 2.70
SYNTHETIC_TRACK_M = 1.55
SYNTHETIC_ROCKER_HEIGHT_M = 0.16
SYNTHETIC_SHOULDER_HEIGHT_M = 0.80
SYNTHETIC_MARGIN_PX = 12

# Three camera heights across three azimuths: the spread REALISM_PLAN.md's Phase
# 1 is about, and between them they reach every rung of the elevation cascade.
# (name, shot angle, nominal elevation in degrees, azimuth away from side-on)
SYNTHETIC_SET: tuple[tuple[str, str, float, float], ...] = (
    ("side-crouching", "side", elevation.CROUCHING_ELEVATION_DEG, 0.0),
    ("side-standing", "side", elevation.STANDING_ELEVATION_DEG, 0.0),
    ("side-raised", "side", elevation.RAISED_ELEVATION_DEG, 0.0),
    ("front-quarter-crouching", "front_quarter", elevation.CROUCHING_ELEVATION_DEG, 45.0),
    ("front-standing", "front", elevation.STANDING_ELEVATION_DEG, 90.0),
)


def synthetic_cutout(elevation_deg: float, azimuth_deg: float) -> Image.Image:
    """
    A drawn RGBA cut-out of a car, seen from a stated camera elevation.

    A cartoon, and it has to be read as one. The silhouette is a rounded body
    with a cabin on top and is not the projection of any real vehicle; what is
    faithful is the geometry the estimator actually reads. The car's dimensions
    come from elevation.py's own reference vehicle rather than being invented
    here, and each wheel is drawn as the ellipse that circle really projects to,
    minor over major = |cos(elevation) * cos(azimuth)|, which is the relationship
    elevation.py documents its departure from REALISM_PLAN.md over.

    Three things encode the nominal elevation, and all three had to, because
    while only the first was drawn a sweep over this fixture measured the drawing
    rather than the estimator — and read as evidence against elevation.py's
    second rung when it was really evidence about what was missing here:

      * Each wheel is the ellipse its circle projects to.
      * The underbody gap closes as the camera rises, following the same
        c - b*tan(theta) that `elevation.UNDERSIDE_GEOMETRY` states, so rung 2
        has something real to read. Drawn at a fixed rocker height it never
        varied, and the rung duly reported nearly the same angle across a whole
        sweep — which looks exactly like an overconfident estimator and was not.
      * The contact line tilts with azimuth. A nearer wheel projects lower than
        a far one, so a quarter-angle car does not stand on a level line, and
        rung 2 declines there as it was written to. Drawn level, it answered in
        precisely the case its own wheelbase test exists to refuse.

    It remains a cartoon: the silhouette is a rounded body with a cabin on top
    and is not the projection of any real vehicle. What is faithful is the
    geometry the estimator reads, and the car's dimensions come from
    elevation.py's reference vehicle rather than being invented here.
    """
    metres_to_px = SYNTHETIC_PIXELS_PER_METRE
    azimuth = math.radians(azimuth_deg)
    cos_azimuth, sin_azimuth = math.cos(azimuth), math.sin(azimuth)

    # The width the body projects to as it turns: 4.70 m side-on falling to
    # 1.83 m head-on, which is the collapse compositing.REFERENCE_VEHICLE_ASPECT
    # is derived from and the reason a gallery has to be sized by height.
    length_m = (
        elevation.REFERENCE_VEHICLE_LENGTH_M * abs(cos_azimuth)
        + elevation.REFERENCE_VEHICLE_WIDTH_M * abs(sin_azimuth)
    )
    height_m = elevation.REFERENCE_VEHICLE_HEIGHT_M

    # Where each of the four wheels lands across the frame, and how near the
    # camera it is. Both are needed: projecting the wheelbase alone would put
    # the pair on top of one another head-on, where what a photograph actually
    # shows is two wheels a track apart, and it is the depth that says which
    # pair the body hides.
    wheels = sorted(
        (
            lateral * cos_azimuth + longitudinal * sin_azimuth,
            longitudinal * cos_azimuth - lateral * sin_azimuth,
        )
        for lateral in (-SYNTHETIC_TRACK_M / 2.0, SYNTHETIC_TRACK_M / 2.0)
        for longitudinal in (-SYNTHETIC_WHEELBASE_M / 2.0, SYNTHETIC_WHEELBASE_M / 2.0)
    )

    half_length = length_m / 2.0
    half_extent_m = max(
        half_length,
        max(abs(offset) for _, offset in wheels) + elevation.WHEEL_DIAMETER_M / 2.0,
    )
    width_px = round(2 * half_extent_m * metres_to_px) + 2 * SYNTHETIC_MARGIN_PX
    height_px = round(height_m * metres_to_px) + 2 * SYNTHETIC_MARGIN_PX
    ground_row = height_px - SYNTHETIC_MARGIN_PX
    centre_column = width_px / 2.0

    def column(offset_m: float) -> float:
        return centre_column + offset_m * metres_to_px

    def row(height_above_ground_m: float) -> float:
        return ground_row - height_above_ground_m * metres_to_px

    canvas = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    body = (*SYNTHETIC_BODY_COLOUR, 255)

    major_px = elevation.WHEEL_DIAMETER_M * metres_to_px
    foreshortening = abs(cos_azimuth) * abs(math.cos(math.radians(elevation_deg)))
    wheel_centre_row = row(elevation.WHEEL_CENTRE_HEIGHT_M)

    camera_height_m = elevation.camera_height_for_elevation(elevation_deg)

    nearest_depth = max(depth for depth, _ in wheels)

    def _drop(depth_m: float) -> float:
        remaining = elevation.TYPICAL_SHOOTING_DISTANCE_M - depth_m
        return 0.0 if remaining <= 0.1 else camera_height_m * depth_m / remaining

    def depth_lift_px(depth_m: float) -> float:
        """
        How much HIGHER a wheel this far behind the nearest one projects.

        A pinhole puts a ground point at distance D below the horizon by f*h/D,
        so wheels at different depths do not share a contact row. Measured
        against the nearest wheel rather than the car's centre, so the car still
        stands on its own ground line and only the far wheels ride up.

        Side-on and end-on the two visible wheels share a depth and this is zero
        for both, which is why those cases keep the level contact line rung 2
        needs. At a quarter angle they separate and no level line exists — which
        is exactly what that rung's wheelbase test refuses, and it should.
        """
        return metres_to_px * (_drop(depth_m) - _drop(nearest_depth))

    def draw_wheel(offset_m: float, clip_the_arch: bool, depth_m: float = 0.0) -> None:
        wheel_column = column(offset_m)
        wheel_centre_row = row(elevation.WHEEL_CENTRE_HEIGHT_M) + depth_lift_px(depth_m)
        for radius_m, colour in (
            (elevation.WHEEL_DIAMETER_M / 2.0, SYNTHETIC_TYRE_COLOUR),
            (SYNTHETIC_RIM_RADIUS_M, SYNTHETIC_RIM_COLOUR),
        ):
            half_major = radius_m * metres_to_px
            half_minor = max(1.0, half_major * foreshortening)
            draw.ellipse(
                [
                    wheel_column - half_major, wheel_centre_row - half_minor,
                    wheel_column + half_major, wheel_centre_row + half_minor,
                ],
                fill=(*colour, 255),
            )
        if clip_the_arch:
            half_minor = max(1.0, major_px / 2.0 * foreshortening)
            draw.rectangle(
                [
                    wheel_column - major_px / 2.0 - 1, wheel_centre_row - half_minor - 1,
                    wheel_column + major_px / 2.0 + 1,
                    wheel_centre_row - half_minor + 2 * half_minor * SYNTHETIC_ARCH_CLIP,
                ],
                fill=body,
            )

    # Far wheels, then the body over them, then the near pair on top, which is
    # the order a photograph presents them in. Drawing all four above the body
    # would show the far side of the car through it at a quarter angle.
    for depth, offset_m in wheels:
        if depth <= 0:
            draw_wheel(offset_m, clip_the_arch=False, depth_m=depth)

    # The lower edge of the body IS the underbody gap rung 2 measures, so it is
    # drawn from that rung's own model rather than at a fixed rocker height:
    # the gap is the clearance less the lever times tan(elevation), closing to
    # nothing once the camera is high enough to see the valance instead of the
    # cavity. Reusing elevation.UNDERSIDE_GEOMETRY means a change to the
    # estimator's constants moves the fixture with it, instead of leaving the
    # two silently describing different cars.
    clearance_m, lever_m = elevation.UNDERSIDE_GEOMETRY[
        "side" if abs(cos_azimuth) > 0.85
        else "end" if abs(cos_azimuth) < 0.35
        else "quarter"
    ]
    gap_m = max(0.0, clearance_m - lever_m * math.tan(math.radians(elevation_deg)))

    draw.rounded_rectangle(
        [
            column(-half_length), row(SYNTHETIC_SHOULDER_HEIGHT_M),
            column(half_length), row(SYNTHETIC_ROCKER_HEIGHT_M),
        ],
        radius=max(2, round(0.18 * metres_to_px)),
        fill=body,
    )
    draw.polygon(
        [
            (column(-half_length * 0.55), row(SYNTHETIC_SHOULDER_HEIGHT_M)),
            (column(-half_length * 0.30), row(height_m)),
            (column(half_length * 0.34), row(height_m)),
            (column(half_length * 0.62), row(SYNTHETIC_SHOULDER_HEIGHT_M)),
        ],
        fill=body,
    )

    # The cavity between the contact patches, filling in as the camera rises.
    # Inset to the wheels on purpose: what closes the gap in a photograph is the
    # far rocker and the underbody coming into view BETWEEN the wheels, and
    # drawing it across them instead would bury the lower part of each ellipse
    # and quietly destroy the measurement rung 1 depends on.
    if gap_m < SYNTHETIC_ROCKER_HEIGHT_M:
        inner = sorted(offset for _, offset in wheels)
        left_edge = inner[0] + elevation.WHEEL_DIAMETER_M / 2.0
        right_edge = inner[-1] - elevation.WHEEL_DIAMETER_M / 2.0
        if right_edge > left_edge:
            draw.rectangle(
                [
                    column(left_edge), row(SYNTHETIC_ROCKER_HEIGHT_M),
                    column(right_edge), row(gap_m),
                ],
                fill=body,
            )

    for depth, offset_m in wheels:
        if depth > 0:
            draw_wheel(offset_m, clip_the_arch=True, depth_m=depth)

    rgb = np.array(canvas.convert("RGB"), dtype=np.uint8)
    alpha = np.array(canvas.getchannel("A"), dtype=np.uint8)
    # The colour is spread outwards before the alpha is feathered, or the soft
    # ring would be transparent black over the top of the paint and every
    # synthetic vehicle would composite with a dark halo — the very artefact
    # compositing.refine_alpha_mask erodes the mask to remove.
    rgb = cv2.dilate(rgb, np.ones((3, 3), dtype=np.uint8), iterations=2)
    alpha = cv2.GaussianBlur(alpha, (0, 0), SYNTHETIC_EDGE_SOFTNESS_PX)

    softened = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    softened.putalpha(Image.fromarray(alpha, mode="L"))
    return softened


def write_synthetic_set(directory: Path) -> list[Path]:
    """
    Draw the smoke-run set into `directory`, tagged so it cannot pass for real.

    Each cut-out gets the synthetic marker inside the PNG and a sidecar carrying
    the shot angle and the elevation it was drawn from. The sidecar is the same
    file format a person can write by hand next to a real photograph, so the
    smoke run exercises exactly the path real inputs take rather than a private
    one of its own.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, angle, elevation_deg, azimuth_deg in SYNTHETIC_SET:
        image = synthetic_cutout(elevation_deg, azimuth_deg)
        marker = PngInfo()
        marker.add_text(SYNTHETIC_PNG_KEY, "1")
        path = directory / f"{name}.png"
        image.save(path, pnginfo=marker)
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "synthetic": True,
                    "angle": angle,
                    "nominal_elevation_deg": round(elevation_deg, 2),
                },
                indent=2,
            )
            + "\n"
        )
        written.append(path)
    return written


# ── Reading the inputs ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Cutout:
    """One input photograph and everything known about it before it is measured.

    `angle` and `vehicle_horizon_ratio` are read rather than derived: nothing in
    this harness classifies a shot angle or finds a horizon, and inventing either
    would be putting a guess into the provenance of a measurement.
    """

    path: Path
    image: Image.Image
    digest: str
    angle: str | None
    synthetic: bool
    nominal_elevation_deg: float | None
    vehicle_horizon_ratio: float | None


def file_digest(path: Path) -> str:
    """A SHA-256 of the file, so two runs can be shown to have used one input."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def read_sidecar(path: Path) -> dict:
    """
    The optional `<name>.json` beside a cut-out, or an empty mapping.

    A malformed sidecar warns and is ignored rather than stopping the run: a
    batch of thirty photographs should not be lost to one stray comma, and the
    photograph it belonged to still measures perfectly well without its angle.
    """
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        loaded = json.loads(sidecar.read_text())
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {sidecar.name} — {exc}", file=sys.stderr)
        return {}
    if not isinstance(loaded, dict):
        print(f"warning: ignoring {sidecar.name} — expected an object", file=sys.stderr)
        return {}
    return loaded


def load_cutouts(directory: Path) -> list[Cutout]:
    """Every cut-out in `directory`, in name order, with its sidecar applied."""
    paths = sorted(
        path for path in directory.iterdir() if path.suffix.lower() in CUTOUT_SUFFIXES
    )
    loaded: list[Cutout] = []
    for path in paths:
        image = Image.open(path)
        image.load()
        if "A" not in image.getbands():
            # Not fatal, but worth saying loudly. Everything downstream treats a
            # missing alpha channel as a fully opaque rectangle: the edge quality
            # comes out at zero and the composite is a photograph pasted on as a
            # block, and both are numbers rather than errors.
            print(
                f"warning: {path.name} has no alpha channel, so it is not a cut-out",
                file=sys.stderr,
            )

        sidecar = read_sidecar(path)
        angle = sidecar.get("angle")
        if angle is not None and angle not in KNOWN_ANGLES:
            print(
                f"warning: {path.name} names an unrecognised shot angle '{angle}'",
                file=sys.stderr,
            )

        loaded.append(
            Cutout(
                path=path,
                image=image.convert("RGBA"),
                digest=file_digest(path),
                angle=angle,
                # Either witness is enough. The sidecar is the one a person
                # writes; the PNG marker is the one that survives the file being
                # copied somewhere else on its own.
                synthetic=bool(sidecar.get("synthetic"))
                or image.info.get(SYNTHETIC_PNG_KEY) == "1",
                nominal_elevation_deg=sidecar.get("nominal_elevation_deg"),
                vehicle_horizon_ratio=sidecar.get("vehicle_horizon_ratio"),
            )
        )
    return loaded


# ── Measuring ──────────────────────────────────────────────────────────────────

def measure(
    cutout: Cutout,
    backdrop: Image.Image,
    preset: compositing.BackdropPreset,
    backdrop_horizon_ratio: float | None = None,
) -> tuple[dict, Image.Image]:
    """
    Composite one cut-out and reduce it to a row of the metrics file.

    Returns the row and the render, so that the caller decides where the picture
    goes and this stays a function a test can call without a directory.
    """
    render, composed = compositing.compose(cutout.image, backdrop, preset, angle=cutout.angle)
    estimate = elevation.estimate_elevation(cutout.image, cutout.angle)

    # Measured on the cut-out and never on the render. A finished composite is
    # opaque everywhere, so metrics.edge_quality finds no boundary in it and
    # returns zeros — which is exactly the score a hopelessly binary matte gets,
    # and would make the mistake invisible in a results table.
    edge = metrics.edge_quality(cutout.image)

    offset = None
    if backdrop_horizon_ratio is not None and cutout.vehicle_horizon_ratio is not None:
        offset = metrics.horizon_offset(
            cutout.vehicle_horizon_ratio,
            backdrop_horizon_ratio,
            composed["output_size"]["height"],
        )

    record = {
        "name": cutout.path.name,
        "sha256": cutout.digest,
        "synthetic": cutout.synthetic,
        "angle": cutout.angle,
        "cutout_size": {"width": cutout.image.width, "height": cutout.image.height},
        # estimate_elevation hands back the inference and not the measurement
        # behind it — the raw axis ratio and the raw underside gap stay inside
        # elevation.py's own rungs — so the method name is recorded beside every
        # figure. A 'wheel_ellipse' row and an 'assumed' row are not the same kind
        # of number, and averaging them without saying so is the easiest way to
        # quote a population prior as an observation.
        "elevation": {
            "degrees": round(estimate.degrees, 2),
            "confidence": round(estimate.confidence, 3),
            "method": estimate.method,
        },
        "edge_quality": {
            "fractional_px": edge.fractional,
            "silhouette_px": edge.silhouette,
            "ratio": round(edge.ratio, 4),
        },
        "composite": composed,
        "horizon_offset_px": None if offset is None else round(offset, 1),
    }
    if cutout.nominal_elevation_deg is not None:
        # Only ever present when something outside the harness knew the truth,
        # which today means a drawn vehicle. It is recorded rather than scored
        # against: a synthetic set cannot tell anyone how accurate the estimator
        # is on photographs.
        record["nominal_elevation_deg"] = round(float(cutout.nominal_elevation_deg), 2)
    return record, render


def summarise(records: list[dict]) -> dict:
    """
    Roll the per-photograph rows up into the figures a phase is judged on.

    Edge quality is pooled from the counts rather than averaged from the ratios,
    which is what metrics.EdgeQuality carries both counts for: averaging ratios
    over a set weights a wing mirror the same as a whole car.
    """
    fractional = sum(row["edge_quality"]["fractional_px"] for row in records)
    silhouette = sum(row["edge_quality"]["silhouette_px"] for row in records)
    degrees = [row["elevation"]["degrees"] for row in records]
    confidences = [row["elevation"]["confidence"] for row in records]
    offsets = [
        row["horizon_offset_px"] for row in records if row["horizon_offset_px"] is not None
    ]

    heights = [row["composite"]["vehicle_height_px"] for row in records]
    try:
        spread = round(metrics.size_spread(heights), 4)
    except ValueError as exc:
        # A height of zero is a photograph that rendered nothing, which is a
        # failed composite rather than an incoherent gallery. Reporting it as a
        # blank with the reason beats losing the other four figures to it.
        print(f"warning: gallery coherence not measured — {exc}", file=sys.stderr)
        spread = None

    return {
        "photographs": len(records),
        "edge_fractional_px": fractional,
        "edge_silhouette_px": silhouette,
        "edge_quality_ratio": round(fractional / silhouette, 4) if silhouette else None,
        "size_spread": spread,
        "mean_elevation_deg": round(sum(degrees) / len(degrees), 2) if degrees else None,
        "mean_elevation_confidence": (
            round(sum(confidences) / len(confidences), 3) if confidences else None
        ),
        "measured_elevations": sum(
            1 for row in records if row["elevation"]["method"] in MEASURED_ELEVATION_METHODS
        ),
        "mean_horizon_offset_px": round(sum(offsets) / len(offsets), 1) if offsets else None,
    }


def build_report(
    *,
    label: str,
    records: list[dict],
    backdrop: dict,
    inputs: dict,
) -> dict:
    """The whole metrics file, provenance first."""
    methods: dict[str, int] = {}
    for row in records:
        method = row["elevation"]["method"]
        methods[method] = methods.get(method, 0) + 1

    return {
        "schema": SCHEMA,
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Repeated at the top level as well as per photograph because this is the
        # field a reader has to see before any figure below it, and burying it in
        # a list of thirty rows would be a good way to have it missed.
        "synthetic": bool(inputs.get("synthetic")),
        "inputs": inputs,
        "backdrop": backdrop,
        "totals": summarise(records),
        "elevation_methods": methods,
        "photographs": records,
    }


# ── Comparing against a saved baseline ─────────────────────────────────────────

# The totals a phase moves, with how many places each is worth quoting to.
COMPARED_TOTALS: tuple[tuple[str, int], ...] = (
    ("edge_quality_ratio", 4),
    ("size_spread", 4),
    ("mean_elevation_deg", 2),
    ("mean_elevation_confidence", 3),
    ("mean_horizon_offset_px", 1),
)


def compare(report: dict, baseline: dict) -> dict:
    """
    The deltas between this run and a saved one, with what invalidates them.

    The warnings are the point of doing this in code rather than by eye. Two
    metrics files always subtract, and the difference is meaningless when they
    were measured over different photographs, against a different backdrop, or
    when one of them was synthetic — all three of which are easy to do by
    accident weeks apart and impossible to spot in a table of numbers.
    """
    warnings: list[str] = []
    if bool(baseline.get("synthetic")) != bool(report.get("synthetic")):
        warnings.append(
            "one of these runs used drawn vehicles and the other did not, so "
            "the deltas below compare two different things"
        )
    if baseline.get("backdrop", {}).get("sha256") != report.get("backdrop", {}).get("sha256"):
        warnings.append(
            "the two runs used different backdrops, so any figure below moved "
            "for that reason as well as for any change to the code"
        )
    if baseline.get("schema") != report.get("schema"):
        warnings.append(
            f"the baseline was written by schema {baseline.get('schema')!r} and "
            f"this run by {report.get('schema')!r}"
        )

    totals: dict[str, dict] = {}
    for key, places in COMPARED_TOTALS:
        before = baseline.get("totals", {}).get(key)
        after = report.get("totals", {}).get(key)
        if before is None or after is None:
            continue
        totals[key] = {
            "before": before,
            "after": after,
            "delta": round(after - before, places),
        }

    before_rows = {row["name"]: row for row in baseline.get("photographs", [])}
    after_rows = {row["name"]: row for row in report.get("photographs", [])}
    photographs = []
    for name in sorted(before_rows.keys() & after_rows.keys()):
        before_row, after_row = before_rows[name], after_rows[name]
        photographs.append({
            "name": name,
            "edge_quality_ratio": {
                "before": before_row["edge_quality"]["ratio"],
                "after": after_row["edge_quality"]["ratio"],
                "delta": round(
                    after_row["edge_quality"]["ratio"] - before_row["edge_quality"]["ratio"], 4
                ),
            },
            "elevation_deg": {
                "before": before_row["elevation"]["degrees"],
                "after": after_row["elevation"]["degrees"],
                "delta": round(
                    after_row["elevation"]["degrees"] - before_row["elevation"]["degrees"], 2
                ),
            },
        })

    only_in_baseline = sorted(before_rows.keys() - after_rows.keys())
    only_in_current = sorted(after_rows.keys() - before_rows.keys())
    if only_in_baseline or only_in_current:
        warnings.append(
            f"{len(only_in_baseline) + len(only_in_current)} photographs appear in "
            "only one of the two runs, so the pooled totals are not over the same set"
        )

    return {
        "baseline": {
            "label": baseline.get("label"),
            "generated_at": baseline.get("generated_at"),
            "synthetic": bool(baseline.get("synthetic")),
            "photographs": baseline.get("totals", {}).get("photographs"),
        },
        "warnings": warnings,
        "totals": totals,
        "photographs": photographs,
        "only_in_baseline": only_in_baseline,
        "only_in_current": only_in_current,
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

SYNTHETIC_BANNER = (
    "SYNTHETIC INPUT — THESE NUMBERS SAY NOTHING ABOUT REALISM.\n"
    "  The vehicles in this run were drawn by the harness, not photographed. A\n"
    "  synthetic run shows that the measuring works end to end; it is not\n"
    "  evidence that a composite looks better, and quoting it in the technical\n"
    "  report as if it were would be dishonest. Re-run against real dealer\n"
    "  cut-outs before any figure below leaves this file."
)


def _figure(value: float | None, places: int) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def render_summary(
    report: dict, comparison: dict | None = None, output_dir: Path | None = None
) -> str:
    """
    The short human-readable summary, derived entirely from the metrics file.

    Taking the whole thing from the report rather than from the run means the
    summary and the numbers cannot disagree, and that a saved metrics file is a
    complete record on its own.
    """
    totals = report.get("totals", {})
    backdrop = report.get("backdrop", {})
    inputs = report.get("inputs", {})
    lines: list[str] = []

    lines.append(f"AutoPivot realism evidence — {report.get('label') or 'unlabelled run'}")
    lines.append(f"{report.get('generated_at')}   schema {report.get('schema')}")
    lines.append("")
    if report.get("synthetic"):
        lines.append(SYNTHETIC_BANNER)
        lines.append("")

    photographs = report.get("photographs", [])
    canvas = photographs[0]["composite"]["output_size"] if photographs else {}
    lines.append(
        f"Inputs     {totals.get('photographs')} cut-outs from {inputs.get('directory')}"
    )
    lines.append(f"Backdrop   {backdrop.get('label')} [{backdrop.get('preset')}], "
                 f"source {backdrop.get('source_width')}x{backdrop.get('source_height')}, "
                 f"rendered at {canvas.get('width')}x{canvas.get('height')}")
    lines.append(f"           {backdrop.get('source')}")
    lines.append("")

    lines.append("Measured")
    lines.append(
        f"  edge quality      {_figure(totals.get('edge_quality_ratio'), 4)}   "
        f"of {totals.get('edge_silhouette_px')} boundary pixels carry fractional alpha"
    )
    lines.append(
        f"  gallery spread    {_figure(totals.get('size_spread'), 4)}   "
        "largest rendered vehicle height over the smallest; 1.0000 is coherent"
    )
    lines.append(
        f"  camera elevation  {_figure(totals.get('mean_elevation_deg'), 2)} deg mean, "
        f"confidence {_figure(totals.get('mean_elevation_confidence'), 3)}"
    )
    methods = ", ".join(
        f"{method} {count}"
        for method, count in sorted(report.get("elevation_methods", {}).items())
    )
    lines.append(f"                    {methods or 'none'}")
    lines.append(
        f"                    {totals.get('measured_elevations')} of "
        f"{totals.get('photographs')} were measured rather than assumed"
    )
    if totals.get("mean_horizon_offset_px") is None:
        lines.append(
            "  horizon offset    not measured. It needs the backdrop's horizon as a "
            "canvas ratio,"
        )
        lines.append(
            "                    which no preset carries yet, and each photograph's own "
            "horizon,"
        )
        lines.append(
            "                    which nothing estimates yet. Both are Phase 1's to "
            "supply; pass"
        )
        lines.append(
            "                    --backdrop-horizon-ratio and a vehicle_horizon_ratio "
            "per sidecar."
        )
    else:
        lines.append(
            f"  horizon offset    {_figure(totals.get('mean_horizon_offset_px'), 1)} px mean; "
            "positive means the vehicle's horizon sits below the backdrop's"
        )
    lines.append("")

    drawn_from = any("nominal_elevation_deg" in row for row in photographs)
    lines.append("Per photograph")
    header = f"  {'name':<32}{'elev':>8}{'conf':>7}  {'method':<15}{'edge':>7}{'height':>8}"
    lines.append(header + (f"{'drawn':>9}" if drawn_from else ""))
    for row in photographs:
        nominal = row.get("nominal_elevation_deg")
        lines.append(
            f"  {row['name'][:31]:<32}"
            f"{row['elevation']['degrees']:>8.2f}"
            f"{row['elevation']['confidence']:>7.2f}  "
            f"{row['elevation']['method']:<15}"
            f"{row['edge_quality']['ratio']:>7.3f}"
            f"{row['composite']['vehicle_height_px']:>8}"
            + ("" if not drawn_from else f"{_figure(nominal, 2):>9}")
        )
    if drawn_from:
        # Said here rather than left for the reader to assume, because the two
        # columns sit next to each other and invite being read as an error. Only
        # the wheel ellipse of a drawn vehicle carries the elevation it was drawn
        # from, so a row answered by any other rung is not being compared with
        # anything at all.
        lines.append(
            "  'drawn' is the elevation the vehicle was drawn from, and only a "
            "wheel_ellipse row"
        )
        lines.append(
            "  is comparable with it. This is not an accuracy score for the "
            "estimator."
        )
    lines.append("")

    if comparison is not None:
        baseline = comparison.get("baseline", {})
        lines.append(
            f"Against {baseline.get('label') or 'the baseline'} "
            f"({baseline.get('generated_at')})"
        )
        for warning in comparison.get("warnings", []):
            lines.append(f"  ! {warning}")
        if not comparison.get("totals"):
            lines.append("  nothing comparable: no total is present in both files")
        for key, places in COMPARED_TOTALS:
            delta = comparison.get("totals", {}).get(key)
            if delta is None:
                continue
            lines.append(
                f"  {key:<28}{_figure(delta['before'], places):>10} → "
                f"{_figure(delta['after'], places):>10}   "
                f"{delta['delta']:+.{places}f}"
            )
        lines.append("")

    if output_dir is not None:
        lines.append("Look at")
        lines.append(
            f"  {output_dir / 'contact-sheet.png'}"
            "\n      every render in one frame, in the order listed above"
        )
        lines.append(
            f"  {output_dir / 'renders'}"
            "\n      the full-size composites, one per cut-out"
        )
        lines.append(
            f"  {output_dir / 'metrics.json'}"
            "\n      the numbers. Keep this one: it is the --baseline for the next run"
        )
    return "\n".join(lines) + "\n"


# ── The renders ────────────────────────────────────────────────────────────────

CONTACT_SHEET_THUMBNAIL_WIDTH = 480
CONTACT_SHEET_COLUMNS = 3
CONTACT_SHEET_GAP = 12
CONTACT_SHEET_BACKGROUND = (24, 24, 26)


def thumbnail(image: Image.Image) -> Image.Image:
    """One cell of the contact sheet.

    Separate from the sheet itself so that a run can reduce each render as it
    finishes it. Holding a listing's worth of full-size composites in memory to
    assemble the sheet at the end is a couple of hundred megabytes, and this is
    meant to run on whatever laptop the person writing the report has.
    """
    return image.convert("RGB").resize(
        (
            CONTACT_SHEET_THUMBNAIL_WIDTH,
            max(1, round(image.height * CONTACT_SHEET_THUMBNAIL_WIDTH / image.width)),
        ),
        Image.LANCZOS,
    )


def contact_sheet(renders: list[Image.Image]) -> Image.Image | None:
    """
    Every render in one frame, so a reviewer opens one file rather than thirty.

    Deliberately unlabelled. Drawing a caption under each cell would need a font
    and the only one PIL is sure to have is unreadable at this scale; the sheet
    is in the same order as the photograph list in the summary, which is said
    where the sheet is named.
    """
    if not renders:
        return None
    cells = [thumbnail(image) for image in renders]
    columns = min(CONTACT_SHEET_COLUMNS, len(cells))
    rows = math.ceil(len(cells) / columns)
    cell_height = max(cell.height for cell in cells)

    sheet = Image.new(
        "RGB",
        (
            columns * CONTACT_SHEET_THUMBNAIL_WIDTH + (columns + 1) * CONTACT_SHEET_GAP,
            rows * cell_height + (rows + 1) * CONTACT_SHEET_GAP,
        ),
        CONTACT_SHEET_BACKGROUND,
    )
    for index, cell in enumerate(cells):
        row, column = divmod(index, columns)
        sheet.paste(
            cell,
            (
                CONTACT_SHEET_GAP + column * (CONTACT_SHEET_THUMBNAIL_WIDTH + CONTACT_SHEET_GAP),
                CONTACT_SHEET_GAP + row * (cell_height + CONTACT_SHEET_GAP),
            ),
        )
    return sheet


# ── Command line ───────────────────────────────────────────────────────────────

HELP_EPILOGUE = """\
what the numbers mean

  edge quality       The share of the cut-out's boundary carrying alpha strictly
                     between 0 and 255, pooled over every photograph in the run.
                     A mask reduced to a yes or a no per pixel scores near zero;
                     genuine matting resolves spokes and aerials and scores high.
                     This is the figure REALISM_PLAN.md's Phase 3 is judged on.
                     Measured on the cut-out, never on the composite, which is
                     opaque everywhere and would score zero however good it is.

  gallery spread     The largest rendered vehicle height in the run over the
                     smallest. 1.0000 means one car comes out one size whatever
                     way it faces, which the project already achieves and which
                     no later phase may regress.

  camera elevation   Where elevation.py thinks the camera was, in degrees above
                     the horizontal through the wheel centre, with the rung that
                     produced it. 'wheel_ellipse' and 'roof_underside' measured
                     something; 'shot_angle' and 'assumed' did not, and the
                     summary counts the two kinds separately for that reason.
                     No rung is allowed to sound confident — read the estimate as
                     "high camera or low camera", not as a number of degrees.

  horizon offset     How far the vehicle's horizon misses the backdrop's, in
                     canvas pixels, positive when the vehicle's sits lower. Blank
                     until both ends of it exist: pass --backdrop-horizon-ratio
                     for the scene, and put "vehicle_horizon_ratio" in a sidecar
                     for each photograph.

sidecars

  Any cut-out may have a <name>.json beside it. Every key is optional:

      {"angle": "side", "vehicle_horizon_ratio": 0.62,
       "synthetic": false, "nominal_elevation_deg": 11.16}

  'angle' is one of front, front_quarter, side, rear_quarter, rear. It sharpens
  both the composite and the elevation estimate; without it both fall back, which
  costs accuracy rather than failing. 'nominal_elevation_deg' is the elevation a
  vehicle is known to have been shot from, which in practice means one that was
  drawn — it is reported beside the estimate and never scored against it.

comparing two runs

  Save the metrics file before a phase starts, then pass it as --baseline
  afterwards and use a different --out so the renders of both survive:

      python -m scripts.realism_report --cutouts ~/cutouts --label before
      python -m scripts.realism_report --cutouts ~/cutouts --label after \\
          --out evidence/after --baseline evidence/metrics.json
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.realism_report",
        # Wrapped by hand: RawDescriptionHelpFormatter is what keeps the epilogue
        # below readable, and it leaves this alone too.
        description=(
            "Composite a folder of cut-out vehicles, measure the result and\n"
            "write the evidence a realism phase is judged on."
        ),
        epilog=HELP_EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--cutouts", type=Path, metavar="DIR",
        help="directory of RGBA cut-outs (.png or .webp), each optionally with a sidecar",
    )
    source.add_argument(
        "--synthetic", action="store_true",
        help=(
            "draw a set of vehicles into <out>/synthetic and measure those. Proves "
            "the harness runs; proves nothing about realism, and every figure is "
            "labelled accordingly"
        ),
    )

    scene = parser.add_mutually_exclusive_group()
    scene.add_argument(
        "--preset",
        default=compositing.STUDIO_FULL.key,
        choices=sorted(compositing.STUDIO_PRESETS),
        help="which measured studio scene to composite onto (default: %(default)s)",
    )
    scene.add_argument(
        "--backdrop", type=Path, metavar="FILE",
        help="a dealership's own backdrop image instead of a studio preset",
    )

    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT_DIR, metavar="DIR",
        help="where the renders, metrics file and summary go (default: %(default)s)",
    )
    parser.add_argument(
        "--label", default="", metavar="TEXT",
        help="what this run is, e.g. 'before phase 1'. Written into the metrics file",
    )
    parser.add_argument(
        "--baseline", type=Path, metavar="FILE",
        help="a metrics file from an earlier run, to report this one as a delta against",
    )
    parser.add_argument(
        "--backdrop-horizon-ratio", type=float, metavar="R",
        help=(
            "the backdrop's horizon measured down the canvas, 0 at the top and 1 at "
            "the bottom. Needed before any horizon offset can be reported"
        ),
    )
    return parser.parse_args(argv)


def resolve_backdrop(
    args: argparse.Namespace,
) -> tuple[Image.Image, compositing.BackdropPreset, dict] | None:
    """The scene to composite onto and its provenance, or None with a reason printed."""
    if args.backdrop is not None:
        if not args.backdrop.is_file():
            print(f"error: no backdrop at {args.backdrop}", file=sys.stderr)
            return None
        try:
            image = Image.open(args.backdrop).convert("RGBA")
        except OSError as exc:
            print(f"error: {args.backdrop} could not be opened — {exc}", file=sys.stderr)
            return None
        preset = compositing.DEALER_BACKDROP
        source, digest = str(args.backdrop), file_digest(args.backdrop)
    else:
        loaded = compositing.load_studio_backdrop(args.preset)
        if loaded is None:
            print(
                f"error: the '{args.preset}' scene is missing from "
                f"{compositing.BACKGROUND_DIR}",
                file=sys.stderr,
            )
            return None
        image, preset = loaded
        path = compositing.BACKGROUND_DIR / preset.filename
        source, digest = str(path), file_digest(path)

    return image, preset, {
        "source": source,
        "sha256": digest,
        "preset": preset.key,
        "label": preset.label,
        # The size of the file, which is not the size of the renders: a preset
        # carrying an output_size composites onto its own canvas whatever the
        # asset measures. Every figure in canvas pixels — the horizon offset
        # above all — belongs to the canvas recorded per photograph, so the two
        # are named differently here rather than both being "width".
        "source_width": image.width,
        "source_height": image.height,
        "horizon_ratio": args.backdrop_horizon_ratio,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir: Path = args.out

    if args.synthetic:
        cutout_dir = output_dir / "synthetic"
        print(f"Drawing {len(SYNTHETIC_SET)} synthetic cut-outs into {cutout_dir}…")
        write_synthetic_set(cutout_dir)
    else:
        cutout_dir = args.cutouts
        if not cutout_dir.is_dir():
            print(f"error: no such directory: {cutout_dir}", file=sys.stderr)
            return 1

    try:
        cutouts = load_cutouts(cutout_dir)
    except OSError as exc:
        print(f"error: could not read {cutout_dir} — {exc}", file=sys.stderr)
        return 1
    if not cutouts:
        suffixes = " or ".join(CUTOUT_SUFFIXES)
        print(f"error: no {suffixes} cut-outs in {cutout_dir}", file=sys.stderr)
        return 1

    baseline = None
    if args.baseline is not None:
        try:
            baseline = json.loads(args.baseline.read_text())
        except (OSError, ValueError) as exc:
            print(
                f"error: could not read the baseline {args.baseline} — {exc}",
                file=sys.stderr,
            )
            return 1

    resolved = resolve_backdrop(args)
    if resolved is None:
        return 1
    backdrop, preset, provenance = resolved

    render_dir = output_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    print(f"Compositing {len(cutouts)} cut-outs onto {preset.label}…")
    records: list[dict] = []
    thumbnails: list[Image.Image] = []
    for cutout in cutouts:
        record, render = measure(cutout, backdrop, preset, args.backdrop_horizon_ratio)
        render_path = render_dir / f"{cutout.path.stem}.png"
        render.save(render_path)
        record["render"] = str(render_path.relative_to(output_dir))
        records.append(record)
        thumbnails.append(thumbnail(render))
        print(f"  {cutout.path.name}  →  {record['render']}")

    sheet = contact_sheet(thumbnails)
    if sheet is not None:
        sheet.save(output_dir / "contact-sheet.png")

    report = build_report(
        label=args.label,
        records=records,
        backdrop=provenance,
        inputs={
            "directory": str(cutout_dir),
            "count": len(cutouts),
            # True if ANY input was drawn. A run is only as trustworthy as its
            # least trustworthy photograph, so one synthetic vehicle in a folder
            # of thirty real ones taints the pooled totals and has to say so.
            "synthetic": any(cutout.synthetic for cutout in cutouts),
        },
    )
    comparison = None
    if baseline is not None:
        comparison = compare(report, baseline)
        report["comparison"] = comparison

    (output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = render_summary(report, comparison, output_dir)
    (output_dir / "summary.txt").write_text(summary)

    print()
    print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
