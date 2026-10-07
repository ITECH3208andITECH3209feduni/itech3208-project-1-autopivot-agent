# Tests for "Include anyway" surviving the next time a photograph is processed.
#
# POST /api/listings/{id}/images/{image_id}/include records a photograph the
# classifier left out as an exterior, so that it can be processed. But the
# pipeline asked the classifier again every time and held the photograph back
# on the fresh verdict, and run_job then wrote that verdict over the dealer's
# choice — so with classification on, an included photograph could never be
# processed at all, and pressing Process quietly undid the include.
#
#     pytest tests/test_include_override.py -v
#
# The database is a real SQLite file opened through database.connection's own
# get_engine, as in tests/test_processing_reliability.py: a run takes sessions
# of its own, on a thread of its own, and every connection to ":memory:" is a
# separate, empty database.
#
# The tests marked as needing the pipeline import autopivot_backend, which
# needs the ML environment, and are skipped without it. No model is loaded:
# every model-backed step is replaced, and the classifier with it.

import io
import threading

import pytest
from fastapi import BackgroundTasks
from PIL import Image as PilImage
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import classification
from api import processing, routes_listings, storage
from api.schemas import ProcessRequest
from database import connection
from database.base import Base
from database.models import Dealership, Image, ProcessingJob, User, VehicleListing

DEALERSHIP_ID = 1
LISTING_ID = 1
USER_ID = 1

# Every wait below is on an event some other step sets. This is only how long
# to wait before concluding that a bug means it never will be.
HANG_GUARD_S = 10

INTERIOR = classification.Classification("interior", 0.91, None, None)


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


def png_bytes(colour):
    buffer = io.BytesIO()
    PilImage.new("RGB", (32, 24), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def add_photograph(factory, index=0, kind=None):
    """Upload one original, optionally already classified. Returns its id."""
    with factory() as session:
        stored = storage.save_image(DEALERSHIP_ID, "original", png_bytes((30 * index, 40, 90)))
        image = Image(
            vehicle_listing_id=LISTING_ID,
            image_type="original",
            image_kind=kind,
            kind_confidence=None if kind is None else 0.64,
            original_filename=f"photo-{index}.png",
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.size_bytes,
            width=stored.width,
            height=stored.height,
        )
        session.add(image)
        session.commit()
        return image.id


def press_process(factory):
    """POST /api/listings/{id}/process, called as the route function, and the
    run it schedules, carried out the way FastAPI would once the response went."""
    background = BackgroundTasks()
    with factory() as session:
        routes_listings.process_listing(
            LISTING_ID, ProcessRequest(), session.get(User, USER_ID), session, background
        )
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)


def include(factory, image_id):
    """POST /api/listings/{id}/images/{image_id}/include, called as the route function."""
    with factory() as session:
        routes_listings.include_image(LISTING_ID, image_id, session.get(User, USER_ID), session)


def kind_of(factory, image_id):
    with factory() as session:
        return session.get(Image, image_id).image_kind


def latest_job(factory, image_id):
    """(status, review_state, whether it has an output) for the newest attempt."""
    with factory() as session:
        job = session.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.input_image_id == image_id)
            .order_by(ProcessingJob.id.desc())
        ).first()
        return job.status, job.review_state, job.output_image_id is not None


# ── Stand-ins ──────────────────────────────────────────────────────────────────

class Processor:
    """
    Stands in for the vision stack and keeps what it was told.

    Reports `kind` for every photograph, as the classifier would. With
    `composite` it finishes the image regardless, the way a processor with no
    kind gate of its own does; without it, it holds every photograph back, the
    way the pipeline holds back one it judged not to be an exterior. `told` is
    the stored kind each call was given. With `hold` the first call waits
    inside the models until the test sets `go`, and `inside` is set once it is
    waiting.
    """

    def __init__(self, kind, composite=True, hold=False):
        self.kind = kind
        self.composite = composite
        self.told = []
        self.inside = threading.Event()
        self.go = threading.Event()
        self._hold = hold

    def process(self, image, background, placement=None, *, stored_kind=None):
        self.told.append(stored_kind)
        if self._hold and len(self.told) == 1:
            self.inside.set()
            self.go.wait(HANG_GUARD_S)
        if not self.composite:
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                image_kind=self.kind,
                kind_confidence=0.91,
                message="This is an interior shot.",
            )
        return processing.ProcessOutcome(
            image_png=png_bytes((200, 30, 30)),
            vehicle_detected=True,
            model_used="stub",
            image_kind=self.kind,
            kind_confidence=0.91,
        )


class Classifier:
    """The classifier's place in the pipeline: one fixed verdict, counted."""

    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        return self.verdict


@pytest.fixture
def pipeline(sessions, monkeypatch):
    """
    The real PipelineProcessor, registered, with every model-backed step
    replaced and the classifier set to `interior` until a test says otherwise.

    What the pipeline decides from those steps — whether to hold a photograph
    back, which angle to composite at — is the code under test, so it is left
    alone. So is the canvas it finishes on: with no backdrop that is plain PIL.
    """
    backend = pytest.importorskip("autopivot_backend")
    classifier = Classifier(INTERIOR)
    angles = []

    def detect_vehicle(image, conf=0.35):
        width, height = image.size
        return {
            "class": "car",
            "score": 0.9,
            "box": {"xmin": 0, "ymin": 0, "xmax": width, "ymax": height},
            "area": float(width * height),
        }

    place_on_backdrop = backend._place_on_backdrop

    def placed(cutout, background, original_size, coords, **options):
        angles.append(options.get("angle"))
        return place_on_backdrop(cutout, background, original_size, coords, **options)

    monkeypatch.setattr(backend, "_classify", classifier)
    monkeypatch.setattr(backend, "_detect_vehicle", detect_vehicle)
    monkeypatch.setattr(backend, "_remove_background", lambda crop: (crop.convert("RGBA"), "stub"))
    monkeypatch.setattr(backend, "_detect_plates", lambda crop: [])
    monkeypatch.setattr(backend, "_estimate_elevation", lambda cutout, angle: None)
    monkeypatch.setattr(backend, "_place_on_backdrop", placed)
    monkeypatch.setattr(processing, "_processor", backend.PipelineProcessor())
    return backend, classifier, angles


# ── Through the real pipeline ──────────────────────────────────────────────────

def test_an_included_photograph_is_processed_the_next_time_round(sessions, pipeline):
    """
    The defect itself. The classifier calls the photograph an interior shot and
    goes on calling it one; the dealer, who knows it is the car, includes it
    and presses Process. It used to be held back again on the classifier's
    fresh verdict, and the verdict written back over the include — so the
    photograph could never be processed, however many times it was included.
    """
    image_id = add_photograph(sessions)
    press_process(sessions)
    assert latest_job(sessions, image_id) == ("completed", "needs_review", False)
    assert kind_of(sessions, image_id) == "interior"

    include(sessions, image_id)
    press_process(sessions)

    assert latest_job(sessions, image_id) == ("completed", "ok", True)
    assert kind_of(sessions, image_id) == "exterior"


def test_a_photograph_the_classifier_excludes_is_still_excluded_the_first_time(
    sessions, pipeline
):
    """Unchanged behaviour: the include lifts the classifier's gate for one
    photograph a dealer chose, and for nothing else."""
    image_id = add_photograph(sessions)

    press_process(sessions)

    assert latest_job(sessions, image_id) == ("completed", "needs_review", False)
    assert kind_of(sessions, image_id) == "interior"


def test_a_photograph_left_out_before_is_judged_again_rather_than_waved_through(
    sessions, pipeline
):
    """
    Only an exterior on record lifts the gate. A photograph an earlier run left
    out is put to the classifier again, which is how an improved classifier
    gets to include it — and how one that still disagrees keeps it out.
    """
    image_id = add_photograph(sessions, kind="unknown")

    press_process(sessions)

    assert latest_job(sessions, image_id) == ("completed", "needs_review", False)
    assert kind_of(sessions, image_id) == "interior"


def test_an_included_photograph_still_gets_its_shot_angle(sessions, pipeline):
    """
    The classifier is not skipped for a photograph already on record as an
    exterior, only its gate: it is also what reports the shot angle, and the
    compositor places and shadows the vehicle by it.
    """
    backend, classifier, angles = pipeline
    classifier.verdict = classification.Classification("exterior", 0.88, "front", 0.72)

    outcome = backend.PipelineProcessor().process(
        png_bytes((10, 20, 30)), None, stored_kind="exterior"
    )

    assert classifier.calls == 1
    assert angles == ["front"]
    assert outcome.detected_angle == "front"


# ── What the orchestrator tells the processor, and keeps from it ───────────────

def test_the_processor_is_told_which_photograph_the_dealer_included(sessions, monkeypatch):
    """
    The processor cannot know about an include unless it is told: the
    photograph's bytes are all it is otherwise given. A photograph nothing has
    classified is sent exactly as before.
    """
    included = add_photograph(sessions, index=0, kind="interior")
    unclassified = add_photograph(sessions, index=1)
    processor = Processor("exterior")
    monkeypatch.setattr(processing, "_processor", processor)

    include(sessions, included)
    press_process(sessions)

    assert processor.told == ["exterior", None]
    assert latest_job(sessions, included) == ("completed", "ok", True)
    assert latest_job(sessions, unclassified) == ("completed", "ok", True)


@pytest.mark.parametrize(
    "composite", [False, True], ids=["held back", "processed regardless"]
)
def test_an_exterior_on_record_is_not_written_over_by_a_later_verdict(
    sessions, monkeypatch, composite
):
    """
    The other half of the defect, in run_job: the verdict belongs to the
    photograph and is written back to it, and an include was simply the first
    thing written over. Whatever a processor says of an included photograph
    now — whether it honoured the include or not — the include stands.
    """
    image_id = add_photograph(sessions, kind="interior")
    monkeypatch.setattr(processing, "_processor", Processor("interior", composite=composite))

    include(sessions, image_id)
    press_process(sessions)

    assert kind_of(sessions, image_id) == "exterior"


def test_a_later_verdict_still_replaces_anything_but_an_exterior(sessions, monkeypatch):
    """Unchanged behaviour: a photograph left out as an interior and now seen
    as an exterior takes the new verdict, confidence and all."""
    image_id = add_photograph(sessions, kind="interior")
    monkeypatch.setattr(processing, "_processor", Processor("exterior"))

    press_process(sessions)

    with sessions() as session:
        image = session.get(Image, image_id)
        assert (image.image_kind, float(image.kind_confidence)) == ("exterior", 0.91)


def test_an_include_made_while_the_photograph_is_in_the_models_is_kept(
    sessions, monkeypatch
):
    """
    The same write, reached by a race. The photograph was read, and its kind
    with it, before the models started; the dealer included it while they
    worked. Deciding from that earlier copy, the run took the photograph to
    have no exterior on record and wrote its verdict over the include.
    """
    image_id = add_photograph(sessions, kind="unknown")
    processor = Processor("interior", composite=False, hold=True)
    monkeypatch.setattr(processing, "_processor", processor)

    run = threading.Thread(target=press_process, args=(sessions,), daemon=True)
    run.start()
    try:
        assert processor.inside.wait(HANG_GUARD_S), "the run never reached the models"
        include(sessions, image_id)
    finally:
        processor.go.set()
        run.join(HANG_GUARD_S)
    assert not run.is_alive(), "the run never finished"

    assert kind_of(sessions, image_id) == "exterior"
