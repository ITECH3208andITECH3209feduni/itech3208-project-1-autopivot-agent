import json
from pathlib import Path

import pytest
from PIL import Image

import compositing
import elevation
from scripts import realism_report


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    """A complete run over drawn vehicles, from the command line inwards."""
    output_dir = tmp_path_factory.mktemp("evidence")
    exit_code = realism_report.main(
        ["--synthetic", "--label", "harness smoke test", "--out", str(output_dir)]
    )
    assert exit_code == 0
    return output_dir


@pytest.fixture(scope="module")
def drawn_report():
    """A report measured in memory, without going near a directory."""
    loaded = compositing.load_studio_backdrop(compositing.STUDIO_FULL.key)
    assert loaded is not None, "the studio backdrop asset is missing"
    backdrop, preset = loaded

    records = []
    for name, angle, degrees, azimuth in realism_report.SYNTHETIC_SET[:2]:
        cutout = realism_report.Cutout(
            path=Path(f"{name}.png"),
            image=realism_report.synthetic_cutout(degrees, azimuth),
            digest="0" * 64,
            angle=angle,
            synthetic=True,
            nominal_elevation_deg=degrees,
            vehicle_horizon_ratio=None,
        )
        record, _ = realism_report.measure(cutout, backdrop, preset)
        records.append(record)

    return realism_report.build_report(
        label="drawn",
        records=records,
        backdrop={"source": "studio-full.png", "sha256": "a" * 64,
                  "preset": preset.key, "label": preset.label,
                  "source_width": backdrop.width, "source_height": backdrop.height,
                  "horizon_ratio": None},
        inputs={"directory": "drawn", "count": len(records), "synthetic": True},
    )


def row(name, *, fractional=100, silhouette=1000, degrees=11.0, confidence=0.2,
        method="assumed", height=500, horizon_offset=None):
    """One photograph's row of the metrics file, with only the fields under test."""
    return {
        "name": name,
        "sha256": "0" * 64,
        "synthetic": False,
        "angle": "side",
        "cutout_size": {"width": 1000, "height": 400},
        "elevation": {"degrees": degrees, "confidence": confidence, "method": method},
        "edge_quality": {
            "fractional_px": fractional,
            "silhouette_px": silhouette,
            "ratio": round(fractional / silhouette, 4) if silhouette else 0.0,
        },
        "composite": {
            "output_size": {"width": 1280, "height": 960},
            "vehicle_height_px": height,
            "contact_y_px": 700,
        },
        "horizon_offset_px": horizon_offset,
    }


def report(rows, *, label="run", synthetic=False, backdrop_digest="a" * 64):
    return realism_report.build_report(
        label=label,
        records=rows,
        backdrop={"source": "studio-full.png", "sha256": backdrop_digest,
                  "preset": "studio_full", "label": "AutoPivot Studio — Full Car",
                  "source_width": 1448, "source_height": 1086, "horizon_ratio": None},
        inputs={"directory": "somewhere", "count": len(rows), "synthetic": synthetic},
    )


# ── Saying that the input was drawn ────────────────────────────────────────────

def test_a_synthetic_run_says_so_in_both_files(synthetic_run):
    """The defect this exists to prevent is a reporting one rather than a coding one:
    figures measured against vehicles this repository drew itself, quoted in the
    technical report as evidence that a composite looks better.
    """
    saved = json.loads((synthetic_run / "metrics.json").read_text())
    summary = (synthetic_run / "summary.txt").read_text()

    assert saved["synthetic"] is True
    assert saved["inputs"]["synthetic"] is True
    assert all(photograph["synthetic"] for photograph in saved["photographs"])
    assert "SYNTHETIC INPUT" in summary
    assert "say nothing about realism" in summary.lower()


def test_a_drawn_cutout_copied_without_its_sidecar_is_still_declared(tmp_path):
    """The way the declaration would realistically be lost: someone copies a
    promising-looking render's cut-out out of the smoke-run directory into their own
    folder of samples, leaving the sidecar behind, and every later run over that
    folder reports drawn vehicles as photographs.
    """
    realism_report.write_synthetic_set(tmp_path)
    for sidecar in tmp_path.glob("*.json"):
        sidecar.unlink()

    loaded = realism_report.load_cutouts(tmp_path)

    assert loaded
    assert all(cutout.synthetic for cutout in loaded)


def test_a_hand_made_cutout_is_not_declared_synthetic(tmp_path):
    """The other half of the same contract, and it is not redundant: a check that
    declared everything synthetic would pass the test above while making the flag
    meaningless, and the harness would then refuse to let any real measurement be
    quoted.
    """
    Image.new("RGBA", (64, 64), (180, 40, 40, 255)).save(tmp_path / "photograph.png")

    loaded = realism_report.load_cutouts(tmp_path)

    assert [cutout.synthetic for cutout in loaded] == [False]


def test_a_malformed_sidecar_is_ignored_rather_than_losing_the_batch(tmp_path):
    """A stray comma in one sidecar must not cost the other twenty-nine photographs."""
    Image.new("RGBA", (64, 64), (180, 40, 40, 255)).save(tmp_path / "photograph.png")
    (tmp_path / "photograph.json").write_text("{not json,}")

    loaded = realism_report.load_cutouts(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].angle is None


# ── The metrics file ───────────────────────────────────────────────────────────

def test_the_metrics_file_round_trips(drawn_report, tmp_path):
    """A metrics file is only useful if it comes back as what went in, because every
    later phase reads one as its baseline.
    """
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(drawn_report, indent=2) + "\n")

    assert json.loads(path.read_text()) == drawn_report


def test_the_summary_is_derived_from_the_metrics_file_alone(drawn_report):
    """The summary is regenerated from a report rather than from the run that produced
    it, so that the two cannot disagree and so that a saved metrics file is a
    complete record.
    """
    reloaded = json.loads(json.dumps(drawn_report))

    assert realism_report.render_summary(reloaded) == realism_report.render_summary(
        drawn_report
    )


def test_the_summary_names_the_files_a_person_should_open(synthetic_run):
    """A directory of renders nobody is told about is not evidence."""
    summary = (synthetic_run / "summary.txt").read_text()

    assert "contact-sheet.png" in summary
    assert "renders" in summary
    assert "metrics.json" in summary
    assert (synthetic_run / "contact-sheet.png").is_file()
    assert len(list((synthetic_run / "renders").glob("*.png"))) == len(
        realism_report.SYNTHETIC_SET
    )


def test_edge_quality_is_pooled_over_the_set_rather_than_averaged():
    """The defect: averaging the per-photograph ratios weights a wing mirror the same as
    a whole car, so one tightly cropped detail shot can carry a whole phase's
    headline figure.
    """
    totals = realism_report.summarise([
        row("whole-car.png", fractional=100, silhouette=10000),
        row("wing-mirror.png", fractional=100, silhouette=100),
    ])

    assert totals["edge_quality_ratio"] == pytest.approx(200 / 10100, abs=1e-4)
    assert totals["edge_fractional_px"] == 200
    assert totals["edge_silhouette_px"] == 10100


def test_an_unmeasured_horizon_is_blank_rather_than_zero(drawn_report):
    """Zero is the one wrong answer here."""
    assert drawn_report["totals"]["mean_horizon_offset_px"] is None
    assert all(
        photograph["horizon_offset_px"] is None
        for photograph in drawn_report["photographs"]
    )
    assert "not measured" in realism_report.render_summary(drawn_report)


def test_a_render_that_produced_nothing_does_not_cost_the_other_measures():
    """metrics.size_spread raises on a rendered height of zero, on the grounds that it
    is a failed job rather than an incoherent gallery.
    """
    totals = realism_report.summarise([
        row("good.png", height=500),
        row("failed.png", height=0),
    ])

    assert totals["size_spread"] is None
    assert totals["edge_quality_ratio"] is not None
    assert totals["photographs"] == 2


def test_the_elevation_rungs_are_counted_separately_from_one_another(drawn_report):
    """'wheel_ellipse' measured a tyre and 'assumed' guessed standing eye level."""
    methods = drawn_report["elevation_methods"]

    assert sum(methods.values()) == drawn_report["totals"]["photographs"]
    assert set(methods) <= set(elevation.ELEVATION_METHODS)
    assert drawn_report["totals"]["measured_elevations"] == sum(
        count for method, count in methods.items()
        if method in realism_report.MEASURED_ELEVATION_METHODS
    )


# ── Comparing a run against a saved baseline ───────────────────────────────────

def test_comparison_reports_the_delta_between_two_runs():
    """The whole reason the harness saves a file."""
    baseline = report([row("a.png", fractional=1000, silhouette=10000, degrees=8.0)])
    current = report([row("a.png", fractional=3000, silhouette=10000, degrees=14.0)])

    deltas = realism_report.compare(current, baseline)

    assert deltas["totals"]["edge_quality_ratio"] == {
        "before": 0.1, "after": 0.3, "delta": 0.2
    }
    assert deltas["totals"]["mean_elevation_deg"]["delta"] == pytest.approx(6.0)
    assert deltas["photographs"][0]["name"] == "a.png"
    assert deltas["photographs"][0]["edge_quality_ratio"]["delta"] == pytest.approx(0.2)
    assert deltas["warnings"] == []


def test_comparison_skips_a_figure_only_one_of_the_runs_has():
    """The horizon offset is the live case: it is blank today and will not be once Phase
    1 measures both ends of it, so the first run that reports one will be compared
    against a baseline that does not.
    """
    baseline = report([row("a.png")])
    current = report([row("a.png", horizon_offset=12.0)])

    deltas = realism_report.compare(current, baseline)

    assert "mean_horizon_offset_px" not in deltas["totals"]
    assert current["totals"]["mean_horizon_offset_px"] == pytest.approx(12.0)


def test_comparison_warns_when_only_one_run_used_drawn_vehicles():
    """Two metrics files always subtract."""
    baseline = report([row("a.png")], synthetic=True)
    current = report([row("a.png")], synthetic=False)

    warnings = realism_report.compare(current, baseline)["warnings"]

    assert any("drawn vehicles" in warning for warning in warnings)


def test_comparison_warns_when_the_two_runs_measured_different_photographs():
    """Pooled totals are only comparable over the same set."""
    baseline = report([row("a.png"), row("b.png")])
    current = report([row("a.png"), row("c.png")])

    deltas = realism_report.compare(current, baseline)

    assert deltas["only_in_baseline"] == ["b.png"]
    assert deltas["only_in_current"] == ["c.png"]
    assert any("only one of the two runs" in warning for warning in deltas["warnings"])
    assert [photograph["name"] for photograph in deltas["photographs"]] == ["a.png"]


def test_comparison_warns_when_the_backdrop_changed():
    """Every geometric figure here is measured against the scene the vehicle was placed
    in.
    """
    baseline = report([row("a.png")], backdrop_digest="a" * 64)
    current = report([row("a.png")], backdrop_digest="b" * 64)

    warnings = realism_report.compare(current, baseline)["warnings"]

    assert any("different backdrops" in warning for warning in warnings)


def test_the_comparison_is_written_into_the_summary(synthetic_run, tmp_path):
    """A delta computed and then printed nowhere is not evidence either."""
    exit_code = realism_report.main([
        "--cutouts", str(synthetic_run / "synthetic"),
        "--out", str(tmp_path / "after"),
        "--baseline", str(synthetic_run / "metrics.json"),
        "--label", "unchanged",
    ])
    assert exit_code == 0

    summary = (tmp_path / "after" / "summary.txt").read_text()
    saved = json.loads((tmp_path / "after" / "metrics.json").read_text())

    assert "edge_quality_ratio" in summary
    assert saved["comparison"]["totals"]["edge_quality_ratio"]["delta"] == 0.0
    assert saved["comparison"]["totals"]["size_spread"]["delta"] == 0.0


# ── The command line ───────────────────────────────────────────────────────────

def test_an_empty_input_directory_exits_non_zero_with_a_reason(tmp_path, capsys):
    """Pointed at the wrong folder, the harness must not write an empty metrics file and
    exit zero.
    """
    exit_code = realism_report.main(["--cutouts", str(tmp_path), "--out", str(tmp_path)])

    assert exit_code == 1
    assert "no" in capsys.readouterr().err.lower()
    assert not (tmp_path / "metrics.json").exists()


def test_a_missing_input_directory_exits_non_zero(tmp_path, capsys):
    exit_code = realism_report.main([
        "--cutouts", str(tmp_path / "absent"), "--out", str(tmp_path)
    ])

    assert exit_code == 1
    assert "no such directory" in capsys.readouterr().err.lower()

