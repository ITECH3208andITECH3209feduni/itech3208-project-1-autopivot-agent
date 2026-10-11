"""Record what a realism change actually did, as numbers and as pictures."""

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

DEFAULT_OUTPUT_DIR = ROOT / "evidence"

SCHEMA = "autopivot.realism-report/1"

SYNTHETIC_PNG_KEY = "autopivot-synthetic"

CUTOUT_SUFFIXES = (".png", ".webp")

KNOWN_ANGLES = tuple(elevation.ANGLE_ELEVATION_PRIOR_DEG)

MEASURED_ELEVATION_METHODS = elevation.MEASURED_METHODS


# ── The synthetic vehicles ─────────────────────────────────────────────────────

SYNTHETIC_PIXELS_PER_METRE = 400

SYNTHETIC_BODY_COLOUR = (176, 62, 58)
SYNTHETIC_TYRE_COLOUR = (28, 28, 30)

SYNTHETIC_RIM_COLOUR = (185, 185, 190)
SYNTHETIC_RIM_RADIUS_M = 0.2032

SYNTHETIC_ARCH_CLIP = 0.15

SYNTHETIC_EDGE_SOFTNESS_PX = 1.4

SYNTHETIC_WHEELBASE_M = 2.70
SYNTHETIC_TRACK_M = 1.55
SYNTHETIC_ROCKER_HEIGHT_M = 0.16
SYNTHETIC_SHOULDER_HEIGHT_M = 0.80
SYNTHETIC_MARGIN_PX = 12

SYNTHETIC_SET: tuple[tuple[str, str, float, float], ...] = (
    ("side-crouching", "side", elevation.CROUCHING_ELEVATION_DEG, 0.0),
    ("side-standing", "side", elevation.STANDING_ELEVATION_DEG, 0.0),
    ("side-raised", "side", elevation.RAISED_ELEVATION_DEG, 0.0),
    ("front-quarter-crouching", "front_quarter", elevation.CROUCHING_ELEVATION_DEG, 45.0),
    ("front-standing", "front", elevation.STANDING_ELEVATION_DEG, 90.0),
)


def synthetic_cutout(elevation_deg: float, azimuth_deg: float) -> Image.Image:
    """A drawn RGBA cut-out of a car, seen from a stated camera elevation."""
    metres_to_px = SYNTHETIC_PIXELS_PER_METRE
    azimuth = math.radians(azimuth_deg)
    cos_azimuth, sin_azimuth = math.cos(azimuth), math.sin(azimuth)

    length_m = (
        elevation.REFERENCE_VEHICLE_LENGTH_M * abs(cos_azimuth)
        + elevation.REFERENCE_VEHICLE_WIDTH_M * abs(sin_azimuth)
    )
    height_m = elevation.REFERENCE_VEHICLE_HEIGHT_M

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
        """How much HIGHER a wheel this far behind the nearest one projects."""
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

    for depth, offset_m in wheels:
        if depth <= 0:
            draw_wheel(offset_m, clip_the_arch=False, depth_m=depth)

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
    rgb = cv2.dilate(rgb, np.ones((3, 3), dtype=np.uint8), iterations=2)
    alpha = cv2.GaussianBlur(alpha, (0, 0), SYNTHETIC_EDGE_SOFTNESS_PX)

    softened = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    softened.putalpha(Image.fromarray(alpha, mode="L"))
    return softened


def write_synthetic_set(directory: Path) -> list[Path]:
    """Draw the smoke-run set into `directory`, tagged so it cannot pass for real."""
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
    """One input photograph and everything known about it before it is measured."""

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
    """The optional `<name>.json` beside a cut-out, or an empty mapping."""
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
    """Composite one cut-out and reduce it to a row of the metrics file."""
    render, composed = compositing.compose(cutout.image, backdrop, preset, angle=cutout.angle)
    estimate = elevation.estimate_elevation(cutout.image, cutout.angle)

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
        record["nominal_elevation_deg"] = round(float(cutout.nominal_elevation_deg), 2)
    return record, render


def summarise(records: list[dict]) -> dict:
    """Roll the per-photograph rows up into the figures a phase is judged on."""
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
        "synthetic": bool(inputs.get("synthetic")),
        "inputs": inputs,
        "backdrop": backdrop,
        "totals": summarise(records),
        "elevation_methods": methods,
        "photographs": records,
    }


# ── Comparing against a saved baseline ─────────────────────────────────────────

COMPARED_TOTALS: tuple[tuple[str, int], ...] = (
    ("edge_quality_ratio", 4),
    ("size_spread", 4),
    ("mean_elevation_deg", 2),
    ("mean_elevation_confidence", 3),
    ("mean_horizon_offset_px", 1),
)


def compare(report: dict, baseline: dict) -> dict:
    """The deltas between this run and a saved one, with what invalidates them."""
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
    """The short human-readable summary, derived entirely from the metrics file."""
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
    """One cell of the contact sheet."""
    return image.convert("RGB").resize(
        (
            CONTACT_SHEET_THUMBNAIL_WIDTH,
            max(1, round(image.height * CONTACT_SHEET_THUMBNAIL_WIDTH / image.width)),
        ),
        Image.LANCZOS,
    )


def contact_sheet(renders: list[Image.Image]) -> Image.Image | None:
    """Every render in one frame, so a reviewer opens one file rather than thirty."""
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

