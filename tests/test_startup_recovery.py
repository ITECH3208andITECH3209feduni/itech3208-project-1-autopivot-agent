# Tests for picking up, as the server starts, the work a stopped one left behind.
#
# A job in the models when the server stopped says "processing" for good, and a
# job queued behind it says "pending" for good: nothing ran at startup, so both
# stayed that way — the listing said "processing", and the web Processing
# screen polled it indefinitely — until somebody happened to press Process on
# that particular vehicle. processing.recover_interrupted_jobs runs as the full
# application starts and settles all of it.
#
#     pytest tests/test_startup_recovery.py -v
#
# The database is a real SQLite file opened through database.connection's own
# get_engine, as in tests/test_processing_reliability.py: the runs recovery
# starts take sessions of their own, on a thread of their own.
#
# The last test enters autopivot_backend's lifespan, which needs the ML
# environment, and is skipped without it. No model is loaded: the one the
# lifespan loads is replaced.

import asyncio
import io
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image as PilImage
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api import processing, storage
from database import connection
from database.base import Base
from database.models import Dealership, Image, ProcessingJob, User, VehicleListing

DEALERSHIP_ID = 1
USER_ID = 1
INTERRUPTED = "Interrupted — the server stopped before it finished."

# Every wait below is on an event some other step sets. This is only how long
# to wait before concluding that a bug means it never will be.
HANG_GUARD_S = 10


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """A session factory over a fresh SQLite file: one dealership, one user."""
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
        session.commit()

    yield factory

    engine.dispose()
    connection.get_engine.cache_clear()


_colours = iter(range(1, 250))


def png_bytes(colour):
    buffer = io.BytesIO()
    PilImage.new("RGB", (32, 24), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def add_listing(factory, listing_id, status):
    with factory() as session:
        session.add(
            VehicleListing(
                id=listing_id,
                dealership_id=DEALERSHIP_ID,
                created_by_user_id=USER_ID,
                title=f"Vehicle {listing_id}",
                make="Mazda",
                model="CX-5",
                year=2021,
                status="draft",
                processing_status=status,
            )
        )
        session.commit()


def add_photograph(factory, listing_id, job_status=None):
    """One original, and optionally the job a stopped server left against it,
    written straight to the table. Returns (image id, the bytes stored)."""
    content = png_bytes((next(_colours), 40, 90))
    with factory() as session:
        stored = storage.save_image(DEALERSHIP_ID, "original", content)
        image = Image(
            vehicle_listing_id=listing_id,
            image_type="original",
            original_filename="photo.png",
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.size_bytes,
            width=stored.width,
            height=stored.height,
        )
        session.add(image)
        session.flush()
        if job_status is not None:
            session.add(
                ProcessingJob(
                    vehicle_listing_id=listing_id,
                    dealership_id=DEALERSHIP_ID,
                    input_image_id=image.id,
                    processing_type="full_pipeline",
                    status=job_status,
                    started_at=(
                        datetime.now(timezone.utc) - timedelta(hours=1)
                        if job_status != "pending" else None
                    ),
                    completed_at=(
                        datetime.now(timezone.utc) - timedelta(minutes=59)
                        if job_status == "completed" else None
                    ),
                    review_state="ok" if job_status == "completed" else None,
                )
            )
        session.commit()
        return image.id, content


def history(factory, listing_id):
    """Every job on a listing, oldest first, per photograph:
    {image id: [(status, error_message), ...]}."""
    with factory() as session:
        found = {}
        for job in session.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.vehicle_listing_id == listing_id)
            .order_by(ProcessingJob.id)
        ).all():
            found.setdefault(job.input_image_id, []).append((job.status, job.error_message))
        return found


def listing_status(factory, listing_id):
    with factory() as session:
        return session.get(VehicleListing, listing_id).processing_status


def finish(runner):
    """Wait for whatever recovery started in the background, if anything."""
    if runner is not None:
        runner.join(HANG_GUARD_S)
        assert not runner.is_alive(), "the resumed runs never finished"


class Pipeline:
    """
    Stands in for the vision stack: no model, no GPU, one fixed composite.

    It counts what it is given, by the bytes of the photograph. With
    `hold_first` its first call waits inside the models until the test sets
    `go`, and `inside` is set once it is waiting.
    """

    def __init__(self, hold_first=False):
        self.calls = Counter()
        self.inside = threading.Event()
        self.go = threading.Event()
        self._hold_first = hold_first
        self._lock = threading.Lock()

    def process(self, image, background, placement=None):
        with self._lock:
            first = not self.calls
            self.calls[image] += 1
        if first and self._hold_first:
            self.inside.set()
            self.go.wait(HANG_GUARD_S)
        return processing.ProcessOutcome(
            image_png=png_bytes((200, 30, 30)), vehicle_detected=True, model_used="stub"
        )


# ── What recovery does ─────────────────────────────────────────────────────────

def test_a_job_the_last_server_had_in_the_models_is_closed_as_interrupted(
    sessions, monkeypatch
):
    """
    Nothing in a freshly started process is working on anything, so a job that
    says "processing" is one the last server never finished. It is closed as
    failed, which is what it is, and the listing stops reading as in progress.

    It is not put back through the models by itself. That photograph was in
    them when the server went down, and if it was the cause, retrying it at
    every start would take the server down at every start. A dealer retries it
    with Process, as any failed photograph is retried.
    """
    add_listing(sessions, 1, status="processing")
    image_id, _ = add_photograph(sessions, 1, job_status="processing")
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)

    finish(processing.recover_interrupted_jobs())

    assert history(sessions, 1) == {image_id: [("failed", INTERRUPTED)]}
    assert listing_status(sessions, 1) == "needs_review"
    assert sum(pipeline.calls.values()) == 0


def test_jobs_left_pending_are_run_without_anyone_pressing_process(sessions, monkeypatch):
    """
    The queue a stopped server left is worked through: every listing with jobs
    still pending gets a run, and each photograph goes through the models once.
    """
    add_listing(sessions, 1, status="processing")
    add_listing(sessions, 2, status="processing")
    first, first_bytes = add_photograph(sessions, 1, job_status="pending")
    second, second_bytes = add_photograph(sessions, 2, job_status="pending")
    third, third_bytes = add_photograph(sessions, 2, job_status="pending")
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)

    finish(processing.recover_interrupted_jobs())

    assert pipeline.calls == {first_bytes: 1, second_bytes: 1, third_bytes: 1}
    assert history(sessions, 1) == {first: [("completed", None)]}
    assert history(sessions, 2) == {
        second: [("completed", None)],
        third: [("completed", None)],
    }
    assert listing_status(sessions, 1) == "complete"
    assert listing_status(sessions, 2) == "complete"


def test_startup_does_not_wait_for_the_jobs_it_resumes(sessions, monkeypatch):
    """
    The runs happen in the background. A startup that waited for them would
    keep the server from answering anything — sign-in included — for as long
    as the models took over every photograph left in the queue.
    """
    add_listing(sessions, 1, status="processing")
    image_id, _ = add_photograph(sessions, 1, job_status="pending")
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    runner = processing.recover_interrupted_jobs()
    try:
        # Recovery has already returned, and the photograph is only now in the
        # models: they are still holding it.
        assert pipeline.inside.wait(HANG_GUARD_S), "the resumed run never reached the models"
        assert history(sessions, 1) == {image_id: [("processing", None)]}
    finally:
        pipeline.go.set()
        finish(runner)

    assert history(sessions, 1) == {image_id: [("completed", None)]}


def test_a_listing_left_saying_processing_with_nothing_in_flight_is_settled(
    sessions, monkeypatch
):
    """
    A server can stop between committing a listing's last job and writing the
    listing's status, which leaves the status saying "processing" over jobs
    that have all finished. Nothing would ever write it again.
    """
    add_listing(sessions, 1, status="processing")
    add_photograph(sessions, 1, job_status="completed")
    monkeypatch.setattr(processing, "_processor", Pipeline())

    finish(processing.recover_interrupted_jobs())

    assert listing_status(sessions, 1) == "complete"


def test_without_a_processor_recovery_changes_nothing(sessions):
    """
    The light API has no processor and never processes anything, so it has no
    business deciding that a job is abandoned — the full application may be
    working on it against the same database.
    """
    add_listing(sessions, 1, status="processing")
    working, _ = add_photograph(sessions, 1, job_status="processing")
    queued, _ = add_photograph(sessions, 1, job_status="pending")

    assert processing.recover_interrupted_jobs() is None

    assert history(sessions, 1) == {
        working: [("processing", None)],
        queued: [("pending", None)],
    }
    assert listing_status(sessions, 1) == "processing"


# ── Where it runs ──────────────────────────────────────────────────────────────

def test_starting_the_full_application_recovers_what_the_last_server_left(
    sessions, monkeypatch
):
    """
    The recovery has to run where the full application starts, once its
    processor is registered — otherwise it is a function nothing calls, and
    the defect is exactly as it was.
    """
    backend = pytest.importorskip("autopivot_backend")
    monkeypatch.setattr(backend, "HF_TOKEN", "")
    monkeypatch.setattr(backend.registry, "_load_birefnet", lambda: None)
    add_listing(sessions, 1, status="processing")
    image_id, _ = add_photograph(sessions, 1, job_status="processing")

    async def start_and_stop():
        async with backend.lifespan(backend.app):
            return history(sessions, 1)

    seen_once_started = asyncio.run(start_and_stop())

    assert seen_once_started == {image_id: [("failed", INTERRUPTED)]}
    assert listing_status(sessions, 1) == "needs_review"
