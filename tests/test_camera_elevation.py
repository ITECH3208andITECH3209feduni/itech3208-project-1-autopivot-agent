# Tests for the camera elevation estimate on its way from the pipeline to the
# job record.
#
#     pytest tests/test_camera_elevation.py -v
#
# Neither end of that journey can be imported here. autopivot_backend.py pulls
# in torch, and api/processing.py talks to PostgreSQL, so both are read as
# source and asserted against with ast — the same approach, and for the same
# reason, as tests/test_migrations.py and tests/test_internal_imports.py.
# database/models.py and elevation.py are imported for real, because neither
# needs a GPU or a database.

import ast
from pathlib import Path

import pytest

import elevation
from database.models import ProcessingJob

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "versions" / "f3b8d05c1e2a_add_camera_elevation.py"
BACKEND = ROOT / "autopivot_backend.py"
ORCHESTRATOR = ROOT / "api" / "processing.py"

ELEVATION_COLUMNS = ("camera_elevation_deg", "elevation_confidence", "elevation_method")

# What database/base.py's naming convention prepends to a check constraint on
# this table, and therefore what the migration spells out in full while the
# model gives only the tail.
CK_PREFIX = "ck_processing_jobs_"


# ── Reading the two files ─────────────────────────────────────────────────────

def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string assignments, so a name held in a variable resolves."""
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def type_signature(type_call: ast.Call) -> tuple:
    """sa.Numeric(4, 2) as ('Numeric', 4, 2); sa.String(length=20) as ('String', 20)."""
    arguments = [ast.literal_eval(argument) for argument in type_call.args]
    arguments += [ast.literal_eval(keyword.value) for keyword in type_call.keywords]
    return (getattr(type_call.func, "attr", None), *arguments)


def model_type_signature(column) -> tuple:
    """The same shape, read off the mapped column instead."""
    name = type(column.type).__name__
    if name == "Numeric":
        return (name, column.type.precision, column.type.scale)
    return (name, column.type.length)


def migration_columns() -> dict[str, tuple]:
    """Every column the migration adds, as name -> (type signature, nullable)."""
    columns: dict[str, tuple] = {}
    for node in ast.walk(parsed(MIGRATION)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "add_column" or len(node.args) < 2:
            continue
        column = node.args[1]
        nullable = next(
            (
                ast.literal_eval(keyword.value)
                for keyword in column.keywords
                if keyword.arg == "nullable"
            ),
            None,
        )
        columns[ast.literal_eval(column.args[0])] = (
            type_signature(column.args[1]),
            nullable,
        )
    return columns


def migration_check_conditions() -> dict[str, str]:
    """Every check constraint the migration creates, by its unprefixed name."""
    tree = parsed(MIGRATION)
    constants = string_constants(tree)

    conditions: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "create_check_constraint":
            continue
        # Always op.f(NAME) here — tests/test_migrations.py is what enforces
        # that, so this only has to unwrap it.
        held = node.args[0].args[0]
        name = (
            constants[held.id] if isinstance(held, ast.Name) else ast.literal_eval(held)
        )
        conditions[name.removeprefix(CK_PREFIX)] = normalised(
            ast.literal_eval(node.args[2])
        )
    return conditions


def model_check_conditions() -> dict[str, str]:
    # SQLAlchemy has already run these through database/base.py's convention, so
    # the prefix comes off here to meet the migration's names on equal terms.
    return {
        constraint.name.removeprefix(CK_PREFIX): normalised(str(constraint.sqltext))
        for constraint in ProcessingJob.__table__.constraints
        if hasattr(constraint, "sqltext")
    }


def normalised(sql: str) -> str:
    """Line breaks in a constraint are formatting, not meaning."""
    return " ".join(sql.split())


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no function named {name!r}")


def calls_to(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        inner
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and name in (getattr(inner.func, "attr", None), getattr(inner.func, "id", None))
    ]


def keyword_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords}


# ── The model and the migration have to describe the same table ───────────────

@pytest.mark.parametrize("name", ELEVATION_COLUMNS)
def test_the_migration_adds_the_column_the_model_declares(name):
    """
    The defect this catches is a column that exists in one file and not the
    other. SQLAlchemy emits an UPDATE naming every mapped column, so a model
    column the migration forgot does not fail at startup or in review — it
    fails on the first real job, after the GPU work is already done, with an
    UndefinedColumn from PostgreSQL and the whole batch marked failed.
    """
    added = migration_columns()
    assert name in added, f"{name} is mapped on ProcessingJob but no migration adds it"

    signature, nullable = added[name]
    column = ProcessingJob.__table__.c[name]
    assert signature == model_type_signature(column)
    assert nullable is column.nullable


@pytest.mark.parametrize(
    "name",
    ("camera_elevation_range", "elevation_confidence_range", "elevation_method_allowed"),
)
def test_the_migration_creates_the_check_constraint_the_model_declares(name):
    """
    The same drift, in the constraints rather than the columns, and quieter:
    the schema comes up without the rule and every value the model claims is
    impossible is accepted for as long as nobody looks.
    """
    from_migration = migration_check_conditions()
    assert name in from_migration, f"the model declares {name} but no migration creates it"
    assert from_migration[name] == model_check_conditions()[name]


def test_the_elevation_range_matches_the_estimators_own_bounds():
    """
    These bounds are written out in models.py and again in the migration rather
    than imported, because elevation.py needs OpenCV and the light API must
    install without it. Duplicated constants drift: widening
    MAX_ELEVATION_DEG alone would leave the estimator returning values the
    database rejects, and the failure would land on a job that had already run
    the whole pipeline successfully.
    """
    condition = model_check_conditions()["camera_elevation_range"]
    expected = (
        f"camera_elevation_deg IS NULL OR camera_elevation_deg BETWEEN "
        f"{int(elevation.MIN_ELEVATION_DEG)} AND {int(elevation.MAX_ELEVATION_DEG)}"
    )
    assert condition == expected


def test_the_method_constraint_lists_exactly_the_cascades_rungs():
    """
    Same duplication, same drift, opposite direction. A fifth rung added to
    elevation.ELEVATION_METHODS without touching the schema makes every
    photograph it answers for fail its insert; a rung removed leaves a value
    the database still accepts and nothing produces.
    """
    condition = model_check_conditions()["elevation_method_allowed"]
    listed = ", ".join(f"'{method}'" for method in elevation.ELEVATION_METHODS)
    assert condition == f"elevation_method IS NULL OR elevation_method IN ({listed})"


@pytest.mark.parametrize("name", ELEVATION_COLUMNS)
def test_the_elevation_columns_are_nullable(name):
    """
    NOT NULL would be unrunnable against a table that already has jobs in it,
    and wrong besides: a photograph that never produced a cutout has nothing to
    estimate from and must record nothing, which is a different outcome from
    the cascade falling through to its assumption.
    """
    assert ProcessingJob.__table__.c[name].nullable


# ── The pipeline measures the photograph, not the studio ──────────────────────

def test_the_pipeline_estimates_the_elevation_before_it_composites():
    """
    The defect this exists to catch is the estimator being moved below
    _place_on_backdrop, which is where a reader tidying the function would
    naturally put it — beside the other reporting. The compositor rescales the
    cutout to stand on the scene's platform, so a tyre measured afterwards has
    the studio's geometry and not the photograph's, and the job would record
    the backdrop's camera height for every vehicle while looking perfectly
    healthy.
    """
    process = function_node(parsed(BACKEND), "process")

    estimated = calls_to(process, "_estimate_elevation")
    composited = calls_to(process, "_place_on_backdrop")
    assert estimated, "PipelineProcessor.process never calls the elevation estimator"
    assert composited, "PipelineProcessor.process never calls the compositor"

    assert max(call.lineno for call in estimated) < min(
        call.lineno for call in composited
    )


def test_the_pipeline_estimates_after_the_plates_are_treated():
    """
    The other half of the same ordering. _apply_plate_treatment returns a new
    cutout rather than editing in place, so an estimate taken before it would
    be measuring an image the rest of the pipeline then discards — the number
    would still look plausible, because a plate blur does not move a tyre edge.
    """
    process = function_node(parsed(BACKEND), "process")

    treated = calls_to(process, "_apply_plate_treatment")
    assert treated, "PipelineProcessor.process never treats the plates"
    assert max(call.lineno for call in treated) < min(
        call.lineno for call in calls_to(process, "_estimate_elevation")
    )


def test_a_run_that_produced_no_cutout_reports_no_elevation():
    """
    The cascade always answers, so it is tempting to fill these in everywhere
    for consistency. That would be a lie on the early returns: an advertisement
    banner and a photograph with no car in it never produce a cutout, so there
    is nothing to have measured, and recording standing eye level for them
    would make "we assumed" indistinguishable from "there was nothing to look
    at" — which is precisely the distinction Phase 1 needs before it shifts a
    backdrop's horizon.
    """
    process = function_node(parsed(BACKEND), "process")
    elevation_fields = set(ELEVATION_COLUMNS)

    empty = [
        call
        for call in calls_to(process, "ProcessOutcome")
        if any(
            keyword.arg == "image_png"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is None
            for keyword in call.keywords
        )
    ]
    assert empty, "no early return was found, so this test is checking nothing"

    for call in empty:
        assert not keyword_names(call) & elevation_fields, (
            f"line {call.lineno}: an outcome with no image reports an elevation "
            "it had no cutout to measure"
        )


def test_a_completed_run_reports_all_three_elevation_fields():
    """
    The degrees alone are unusable. Without the confidence a caller cannot
    refuse a weak estimate, and without the method it cannot tell a measured
    tyre from an assumption — so reporting one of the three and not the others
    is the same as reporting none of them.
    """
    process = function_node(parsed(BACKEND), "process")

    produced = [
        call
        for call in calls_to(process, "ProcessOutcome")
        if any(
            keyword.arg == "vehicle_detected"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in call.keywords
        )
    ]
    assert len(produced) == 1, "expected exactly one successful outcome to check"
    assert set(ELEVATION_COLUMNS) <= keyword_names(produced[0])


# ── The orchestrator writes them down ─────────────────────────────────────────

@pytest.mark.parametrize("name", ELEVATION_COLUMNS)
def test_run_job_copies_the_estimate_onto_the_job(name):
    """
    The failure here is silent in a way the others are not. A field added to
    ProcessOutcome and never copied across in run_job costs nothing at runtime:
    the pipeline measures the elevation, the outcome carries it, the job is
    written without it and the columns stay null. Nothing raises, nothing is
    logged, and the evidence Phase 1 is meant to be judged on simply is not
    there when someone goes looking for it.
    """
    run_job = function_node(parsed(ORCHESTRATOR), "run_job")

    copied = {
        node.targets[0].attr: node.value.attr
        for node in ast.walk(run_job)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Attribute)
        and isinstance(node.targets[0].value, ast.Name)
        and node.targets[0].value.id == "job"
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "outcome"
    }

    assert copied.get(name) == name
