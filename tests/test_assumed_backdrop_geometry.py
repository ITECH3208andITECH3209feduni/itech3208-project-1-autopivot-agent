# Tests for keeping a backdrop's guessed geometry out of the compositor.
#
# backdrop_analysis.analyse never declines. A backdrop it cannot read — a
# seamless white cyclorama has no lines to converge and no junction to find —
# is stored with the fallback horizon of 0.5 and floor of 0.84, marked
# method "assumed" at confidence 0, so that a dealer can be shown a guess as a
# guess. The pipeline carried only the two ratios, so the compositor took them
# for a measurement: the ground line moved off the one that shipped, and with a
# measured camera elevation the scene was slid and enlarged toward a horizon
# nobody had found — for a backdrop promised to compose exactly as before.
#
#     pytest tests/test_assumed_backdrop_geometry.py -v
#
# The rule, which the first test spells out case by case:
#
#   * A dealer's hand correction is always used, whatever the analyser said
#     before it. The correction route sets both confidences to 1 and leaves the
#     analyser's method in place, so an unreadable backdrop that was corrected
#     still says "assumed".
#   * Otherwise a horizon is used only when it was measured — a vanishing point
#     with a confidence above zero. "assumed" is the fallback constant, and
#     "floor_junction" is the floor's row standing in for eye level because no
#     lines converged: an inference from the floor, which the analyser itself
#     calls weaker than a vanishing point, not a reading of the horizon. Sliding
#     the scene on it would move a dealer's room by an assumption about rooms in
#     general, the mistake elevation.MEASURED_METHODS exists to keep a camera
#     elevation from making.
#   * A floor is used when the analyser found one: a confidence above zero. The
#     fallback floor is stored at exactly zero.
#
# The rule lives on processing.BackdropPlacement, which the light API can
# import, so it is checked without the ML environment. The tests that go on
# through autopivot_backend's compositor need that environment and are skipped
# without it: every model-backed step is replaced, and only compositing is real.
#
# The database is a real SQLite file opened through database.connection's own
# get_engine, as in tests/test_processing_reliability.py, because the run a
# press starts takes sessions of its own.

import io
import itertools

import numpy as np
import pytest
from fastapi import BackgroundTasks
from PIL import Image as PilImage
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import compositing
import elevation
from api import processing, routes_listings, storage
from api.processing import BackdropPlacement
from api.schemas import ProcessRequest
from database import connection
from database.base import Base
from database.models import Backdrop, Dealership, Image, ProcessingJob, User, VehicleListing

DEALERSHIP_ID = 1
LISTING_ID = 1
USER_ID = 1

_backdrop_names = (f"Backdrop {number}" for number in itertools.count(1))

# Each kind of backdrop row, as the analyser or the correction route leaves its
# geometry columns.
NEVER_MEASURED = {}
UNREADABLE = dict(
    horizon_y_ratio=0.5, horizon_method="assumed", horizon_confidence=0.0,
    floor_top_y_ratio=0.84, floor_confidence=0.0,
)
MEASURED = dict(
    horizon_y_ratio=0.444, horizon_method="vanishing_point", horizon_confidence=0.81,
    floor_top_y_ratio=0.90, floor_confidence=0.93,
)
LINES_BUT_NO_FLOOR = dict(
    horizon_y_ratio=0.444, horizon_method="vanishing_point", horizon_confidence=0.81,
    floor_top_y_ratio=0.84, floor_confidence=0.0,
)
FLOOR_BUT_NO_LINES = dict(
    horizon_y_ratio=0.906, horizon_method="floor_junction", horizon_confidence=0.5,
    floor_top_y_ratio=0.906, floor_confidence=1.0,
)
CORRECTED_BY_HAND = dict(
    horizon_y_ratio=0.42, horizon_method="assumed", horizon_confidence=1.0,
    floor_top_y_ratio=0.90, floor_confidence=1.0, geometry_overridden=True,
)
CORRECTED_BEFORE_EVER_MEASURED = dict(
    horizon_y_ratio=0.42, horizon_confidence=1.0,
    floor_top_y_ratio=0.90, floor_confidence=1.0, geometry_overridden=True,
)
# What backdrop_analysis measures for the bundled studio-full.png.
STUDIO_AS_MEASURED = dict(
    horizon_y_ratio=0.493, horizon_method="vanishing_point", horizon_confidence=0.059,
    floor_top_y_ratio=0.602, floor_confidence=0.962,
)


# ── The rule ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "geometry, horizon, floor",
    [
        (NEVER_MEASURED, None, None),
        (UNREADABLE, None, None),
        (MEASURED, 0.444, 0.90),
        (LINES_BUT_NO_FLOOR, 0.444, None),
        (FLOOR_BUT_NO_LINES, None, 0.906),
        (CORRECTED_BY_HAND, 0.42, 0.90),
        (CORRECTED_BEFORE_EVER_MEASURED, 0.42, 0.90),
    ],
    ids=[
        "never measured",
        "unreadable",
        "measured",
        "lines but no floor",
        "floor but no lines",
        "corrected by hand",
        "corrected before ever measured",
    ],
)
def test_only_what_was_measured_or_set_by_hand_reaches_the_compositor(
    geometry, horizon, floor
):
    placement = BackdropPlacement(**geometry)

    assert placement.measured_horizon_y_ratio == horizon
    assert placement.measured_floor_top_y_ratio == floor


# ── Through the orchestrator ───────────────────────────────────────────────────

@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """A session factory over a fresh SQLite file: one dealership, one user, one listing."""
    monkeypatch.setattr(storage, "STORAGE_ROOT", (tmp_path / "storage").resolve())
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+pysqlite:///{(tmp_path / 'autopivot.db').as_posix()}"
    )
    connection.get_engine.cache_clear()
    engine = connection.get_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(processing, "_processor", None)

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        session.add(Dealership(id=DEALERSHIP_ID, name="Bayside Motors", status="active"))
        session.add(
            User(
                id=USER_ID,
                dealership_id=DEALERSHIP_ID,
                email="dana@bayside.test",
                password_hash="x",
                first_name="Dana",
                last_name="Reid",
                role="dealership_admin",
            )
        )
        session.add(
            VehicleListing(
                id=LISTING_ID,
                dealership_id=DEALERSHIP_ID,
                created_by_user_id=USER_ID,
                title="2021 Mazda CX-5",
                make="Mazda",
                model="CX-5",
                year=2021,
                status="draft",
                processing_status="pending",
            )
        )
        session.commit()

    yield factory

    engine.dispose()
    connection.get_engine.cache_clear()


def encoded(image, tag=""):
    """PNG bytes. A tag changes the bytes, and so the storage path, but not a pixel."""
    info = PngInfo()
    info.add_text("tag", tag)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def gradient_scene(size=(400, 300)):
    """Shaded top to bottom, so two different crops of it cannot look alike."""
    return PilImage.linear_gradient("L").resize(size).convert("RGB")


def studio_scene():
    path = compositing.BACKGROUND_DIR / compositing.STUDIO_FULL.filename
    return PilImage.open(io.BytesIO(path.read_bytes())).convert("RGB")


def add_backdrop(factory, name, geometry, scene=None):
    """A backdrop row, its geometry columns as given."""
    with factory() as session:
        content = encoded(scene if scene is not None else gradient_scene())
        stored = storage.save_image(DEALERSHIP_ID, "backdrop", content)
        backdrop = Backdrop(
            dealership_id=DEALERSHIP_ID,
            name=name,
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            suits_angles=[],
            **geometry,
        )
        session.add(backdrop)
        session.commit()
        return backdrop.id


def add_photograph(factory, tag):
    """The same car every time; `tag` only keeps the uploads apart."""
    with factory() as session:
        content = encoded(PilImage.new("RGB", (200, 80), (180, 40, 40)), tag)
        stored = storage.save_image(DEALERSHIP_ID, "original", content)
        image = Image(
            vehicle_listing_id=LISTING_ID,
            image_type="original",
            original_filename=f"{tag}.png",
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.size_bytes,
            width=stored.width,
            height=stored.height,
        )
        session.add(image)
        session.commit()
        return image.id


def press_process(factory, backdrop_id):
    """POST /api/listings/{id}/process with a backdrop, called as the route
    function, and the run it schedules, carried out once the response went."""
    background = BackgroundTasks()
    with factory() as session:
        routes_listings.process_listing(
            LISTING_ID,
            ProcessRequest(backdrop_id=backdrop_id),
            session.get(User, USER_ID),
            session,
            background,
        )
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)


def processed_on(factory, geometry, scene=None):
    """Process one photograph on a new backdrop with this geometry. Returns the
    composite the pipeline stored."""
    backdrop_id = add_backdrop(factory, next(_backdrop_names), geometry, scene)
    image_id = add_photograph(factory, tag=str(backdrop_id))
    press_process(factory, backdrop_id)
    with factory() as session:
        job = session.scalars(
            select(ProcessingJob).where(ProcessingJob.input_image_id == image_id)
        ).one()
        assert (job.status, job.review_state) == ("completed", "ok"), job.error_message
        output = session.get(Image, job.output_image_id)
        return np.asarray(PilImage.open(storage.resolve(output.storage_path)))


class Recorder:
    """Stands in for the vision stack and keeps the placement it was given."""

    def __init__(self):
        self.placements = []

    def process(self, image, background, placement=None):
        self.placements.append(placement)
        return processing.ProcessOutcome(
            image_png=encoded(PilImage.new("RGB", (32, 24), (200, 30, 30))),
            vehicle_detected=True,
            model_used="stub",
        )


def test_the_pipeline_is_told_which_backdrop_geometry_was_only_assumed(
    sessions, monkeypatch
):
    """
    The ratios alone cannot say whether anybody found them, and run_job passed
    on nothing else: the pipeline could not tell an unreadable backdrop's
    fallback from a measurement. The other half is the correction, whose
    method still says "assumed" beside confidences of 1.
    """
    recorder = Recorder()
    monkeypatch.setattr(processing, "_processor", recorder)

    for geometry in (UNREADABLE, FLOOR_BUT_NO_LINES, CORRECTED_BY_HAND):
        backdrop_id = add_backdrop(sessions, next(_backdrop_names), geometry)
        add_photograph(sessions, tag=str(backdrop_id))
        press_process(sessions, backdrop_id)

    assert [
        (placement.measured_horizon_y_ratio, placement.measured_floor_top_y_ratio)
        for placement in recorder.placements
    ] == [(None, None), (None, 0.906), (0.42, 0.90)]


# ── On to the compositor ───────────────────────────────────────────────────────

@pytest.fixture
def composed(sessions, monkeypatch):
    """
    The real PipelineProcessor, registered, with every model-backed step
    replaced and compositing left real. The camera elevation is one read off
    the wheels, the kind allowed to slide the scene, so a horizon handed to the
    compositor shows. Returns what compose was handed and reported, per call.
    """
    backend = pytest.importorskip("autopivot_backend")

    def detect_vehicle(image, conf=0.35):
        width, height = image.size
        return {
            "class": "car",
            "score": 0.9,
            "box": {"xmin": 0, "ymin": 0, "xmax": width, "ymax": height},
            "area": float(width * height),
        }

    calls = []
    compose = compositing.compose

    def recording(cutout, backdrop, preset=compositing.DEALER_BACKDROP, **options):
        result, meta = compose(cutout, backdrop, preset, **options)
        calls.append((preset, meta))
        return result, meta

    monkeypatch.setattr(backend, "_classify", lambda image: None)
    monkeypatch.setattr(backend, "_detect_vehicle", detect_vehicle)
    monkeypatch.setattr(backend, "_remove_background", lambda crop: (crop.convert("RGBA"), "stub"))
    monkeypatch.setattr(backend, "_detect_plates", lambda crop: [])
    monkeypatch.setattr(
        backend,
        "_estimate_elevation",
        lambda cutout, angle: elevation.ElevationEstimate(
            degrees=elevation.RAISED_ELEVATION_DEG, confidence=0.6, method="wheel_ellipse"
        ),
    )
    monkeypatch.setattr(compositing, "compose", recording)
    monkeypatch.setattr(processing, "_processor", backend.PipelineProcessor())
    return calls


def test_an_unreadable_backdrop_composes_exactly_like_an_unmeasured_one(sessions, composed):
    """
    The defect itself. The analyser's fallback is the geometry that shipped,
    and the promise was that a backdrop it could not read would compose exactly
    as one nobody had measured. Taken for a measurement, it stood the vehicle
    on a line of its own and slid the scene toward a horizon nobody found.
    """
    never_measured = processed_on(sessions, NEVER_MEASURED)
    unreadable = processed_on(sessions, UNREADABLE)

    (_, never_measured_meta), (preset, unreadable_meta) = composed
    assert preset is compositing.DEALER_BACKDROP
    assert unreadable_meta == never_measured_meta
    assert np.array_equal(unreadable, never_measured)


@pytest.mark.parametrize(
    "geometry, horizon, ground",
    [
        # 0.90 + 0.06 x (1 - 0.90): FLOOR_CONTACT_MARGIN of the way down the floor.
        (MEASURED, 0.444, 0.906),
        (CORRECTED_BY_HAND, 0.42, 0.906),
    ],
    ids=["measured", "corrected by hand"],
)
def test_measured_and_corrected_geometry_is_still_used(
    sessions, composed, geometry, horizon, ground
):
    processed_on(sessions, geometry)

    ((preset, meta),) = composed
    assert preset.horizon_y_ratio == pytest.approx(horizon)
    assert preset.ground_y_ratio == pytest.approx(ground)
    assert meta["horizon_residual_px"] is not None, "the scene was aligned to the horizon"


@pytest.mark.parametrize(
    "geometry", [UNREADABLE, STUDIO_AS_MEASURED], ids=["unreadable", "as measured"]
)
def test_an_upload_of_the_bundled_studio_is_still_recognised(sessions, composed, geometry):
    """compositing recognises a dealer's upload of the bundled studio from the
    dealer preset, measured or not; handing it the plain one must not stop it."""
    processed_on(sessions, geometry, scene=studio_scene())

    ((_, meta),) = composed
    assert meta["backdrop_style"] == compositing.STUDIO_FULL.key
