# Tests for how a listing's processing run survives what a dealer can do to it
# while it is going: delete a photograph, press Process again, or come back to
# a listing a stopped server left half-done.
#
#     pytest tests/test_processing_reliability.py -v
#
# The database is a real SQLite file, opened through database.connection's own
# get_engine so it carries the production pragmas — foreign keys, WAL and the
# busy timeout. In-memory SQLite will not do here: the runs under test take
# their own connections on their own threads, and every connection to
# ":memory:" is a separate, empty database.
#
# Overlaps are forced with events, never with timing. The stand-in pipeline can
# hold its first photograph "inside the models" until the test lets it go, and
# the second run, the second press or the deletion is made to land in exactly
# that window — so each interleaving happens the same way on every run.

import io
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks
from PIL import Image as PilImage
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

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


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """A session factory over a fresh SQLite file: one dealership, one user, one listing."""
    # Photographs are written to and read from disk for real, so the storage
    # root goes somewhere nothing else lives.
    monkeypatch.setattr(storage, "STORAGE_ROOT", (tmp_path / "storage").resolve())

    # run_listing_jobs opens its own sessions through get_engine, which is
    # cached for the life of the process. The cache is cleared on both sides so
    # the engine built here is the one the runs see, and so no later test is
    # left holding a database that has been deleted.
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+pysqlite:///{(tmp_path / 'autopivot.db').as_posix()}"
    )
    connection.get_engine.cache_clear()
    engine = connection.get_engine()
    Base.metadata.create_all(engine)

    # The processor is process-wide state. Registered per test, and put back.
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


def add_photographs(factory, count, first=0):
    """Upload `count` distinct originals. Returns {image id: the bytes stored}.

    `first` numbers them on from photographs added earlier: the bytes are drawn
    from the number, and two uploads with the same bytes share a storage path.
    """
    contents = {}
    with factory() as session:
        for index in range(first, first + count):
            content = png_bytes((30 * index, 40, 90))
            stored = storage.save_image(DEALERSHIP_ID, "original", content)
            image = Image(
                vehicle_listing_id=LISTING_ID,
                image_type="original",
                original_filename=f"photo-{index}.png",
                storage_path=stored.storage_path,
                mime_type=stored.mime_type,
                file_size_bytes=stored.size_bytes,
                width=stored.width,
                height=stored.height,
            )
            session.add(image)
            session.flush()
            contents[image.id] = content
        session.commit()
    return contents


def add_job(factory, image_id, status, started_at=None):
    """A job written straight to the table — standing in for one an earlier
    server process queued, or started, and never got to finish."""
    with factory() as session:
        job = ProcessingJob(
            vehicle_listing_id=LISTING_ID,
            dealership_id=DEALERSHIP_ID,
            input_image_id=image_id,
            processing_type="full_pipeline",
            status=status,
            started_at=started_at,
        )
        session.add(job)
        session.get(VehicleListing, LISTING_ID).processing_status = "processing"
        session.commit()
        return job.id


def queue_everything(factory):
    with factory() as session:
        jobs = processing.create_jobs(session, session.get(VehicleListing, LISTING_ID), None)
        session.commit()
        return [job.id for job in jobs]


def press_process(factory):
    """POST /api/listings/{id}/process, called as the route function.

    Returns the summary it answered with and the background tasks it
    scheduled, which FastAPI would have run after sending the response.
    """
    background = BackgroundTasks()
    with factory() as session:
        summary = routes_listings.process_listing(
            LISTING_ID, ProcessRequest(), session.get(User, USER_ID), session, background
        )
    return summary, background


def run_scheduled(background):
    """What FastAPI does with the tasks once the response has gone."""
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)


def delete_photograph(factory, image_id):
    """DELETE /api/listings/{id}/images/{image_id}, called as the route function."""
    with factory() as session:
        routes_listings.delete_image(LISTING_ID, image_id, session.get(User, USER_ID), session)


def history(factory):
    """Every job, oldest first, per photograph: {image id: [(status, review_state), ...]}."""
    with factory() as session:
        found = {}
        for job in session.scalars(select(ProcessingJob).order_by(ProcessingJob.id)).all():
            found.setdefault(job.input_image_id, []).append((job.status, job.review_state))
        return found


def listing_status(factory):
    with factory() as session:
        return session.get(VehicleListing, LISTING_ID).processing_status


class Pipeline:
    """
    Stands in for the vision stack: no model, no GPU, one fixed composite.

    It counts what it is given, by the bytes of the photograph, so a count of
    two means one photograph went through the models twice. With `hold_first`
    its first call waits inside the models until the test sets `go` — the
    window the tests land a second run, a second press or a deletion in — and
    `inside` is set once that call is waiting. `first_finds_nothing` makes that
    first call report no vehicle, the outcome that ends in needs_review.
    """

    def __init__(self, hold_first=False, first_finds_nothing=False):
        self.calls = Counter()
        self.inside = threading.Event()
        self.go = threading.Event()
        self._hold_first = hold_first
        self._first_finds_nothing = first_finds_nothing
        self._lock = threading.Lock()

    def process(self, image, background, placement=None):
        with self._lock:
            first = not self.calls
            self.calls[image] += 1
        if first and self._hold_first:
            self.inside.set()
            self.go.wait(HANG_GUARD_S)
        if first and self._first_finds_nothing:
            return processing.ProcessOutcome(
                image_png=None,
                vehicle_detected=False,
                message="No vehicle detected in this photograph.",
            )
        return processing.ProcessOutcome(
            image_png=png_bytes((200, 30, 30)), vehicle_detected=True, model_used="stub"
        )


class InThread(threading.Thread):
    """Runs a call on a thread of its own, as FastAPI's threadpool runs a
    background task, and keeps whatever it raised for the test to look at."""

    def __init__(self, call):
        super().__init__(daemon=True)
        self._call = call
        self.error = None

    def run(self):
        try:
            self._call()
        except BaseException as exc:
            self.error = exc

    def finish(self):
        self.join(HANG_GUARD_S)
        assert not self.is_alive(), "the run never finished"


def listing_run():
    return InThread(lambda: processing.run_listing_jobs(LISTING_ID))


# ── Deleting a photograph while its listing is processing ─────────────────────

def test_deleting_a_queued_photograph_mid_run_leaves_the_rest_to_finish(sessions, monkeypatch):
    """
    The defect this exists to catch. The run read its list of jobs once, up
    front, and deleting a photograph deletes its job with it. When the run
    reached that job, marking it started updated no row; SQLAlchemy raised
    StaleDataError outside the job's own error handling, and the whole run
    ended there. Every job after it stayed pending for good, the listing said
    "processing" for good, and the Processing screen polled for good.
    """
    photographs = list(add_photographs(sessions, 4))
    queue_everything(sessions)
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    run = listing_run()
    run.start()
    try:
        assert pipeline.inside.wait(HANG_GUARD_S), "the run never reached the models"
        # The first photograph is in the models; the dealer deletes the third.
        delete_photograph(sessions, photographs[2])
    finally:
        pipeline.go.set()
        run.finish()

    assert run.error is None
    assert history(sessions) == {
        photographs[0]: [("completed", "ok")],
        photographs[1]: [("completed", "ok")],
        photographs[3]: [("completed", "ok")],
    }
    assert listing_status(sessions) == "complete"


def test_deleting_the_photograph_being_processed_does_not_stop_the_run(sessions, monkeypatch):
    """
    The same deletion, landing on the job that is running. The models come
    back to find their job gone. A "no vehicle found" outcome is recorded
    without a flush inside the job's error handling, so the missing row
    surfaced at the flush after it — outside that handling — and stopped the
    run just the same.
    """
    photographs = list(add_photographs(sessions, 3))
    queue_everything(sessions)
    pipeline = Pipeline(hold_first=True, first_finds_nothing=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    run = listing_run()
    run.start()
    try:
        assert pipeline.inside.wait(HANG_GUARD_S), "the run never reached the models"
        delete_photograph(sessions, photographs[0])
    finally:
        pipeline.go.set()
        run.finish()

    assert run.error is None
    assert history(sessions) == {
        photographs[1]: [("completed", "ok")],
        photographs[2]: [("completed", "ok")],
    }
    assert listing_status(sessions) == "complete"


def test_run_job_keeps_its_promise_not_to_raise_when_its_job_goes_mid_run(
    sessions, monkeypatch
):
    """
    The same deletion one level down, where the fix for it lives. run_job
    promises never to raise, and the run relies on that promise; for a "no
    vehicle found" outcome it broke it, because the flush that met the missing
    row came after the error handling rather than inside it.
    """
    add_photographs(sessions, 1)
    (job_id,) = queue_everything(sessions)
    pipeline = Pipeline(hold_first=True, first_finds_nothing=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    with sessions() as session:
        job = session.get(ProcessingJob, job_id)
        run = InThread(lambda: processing.run_job(session, job))
        run.start()
        try:
            assert pipeline.inside.wait(HANG_GUARD_S), "the job never reached the models"
            delete_photograph(sessions, job.input_image_id)
        finally:
            pipeline.go.set()
            run.finish()

    assert run.error is None
    assert history(sessions) == {}


def test_deleting_the_last_unfinished_photograph_settles_the_listing(sessions, monkeypatch):
    """
    With no run going there is nothing to roll the listing up afterwards, so
    the deletion has to. Here the photograph a stopped server left queued is
    deleted: before, the listing went on saying "processing" with nothing left
    to process — the mobile app polling it for good, and Process answering
    that every photograph was already done.
    """
    add_photographs(sessions, 1)
    queue_everything(sessions)
    monkeypatch.setattr(processing, "_processor", Pipeline())
    processing.run_listing_jobs(LISTING_ID)
    (later,) = add_photographs(sessions, 1, first=1)
    add_job(sessions, later, status="pending")

    delete_photograph(sessions, later)

    assert listing_status(sessions) == "complete"


def test_a_run_that_finds_nothing_left_still_settles_the_listing(sessions, monkeypatch):
    """
    A run writes the listing's status after every job and once more when none
    are left, and that last one is not redundant: the jobs still to come when
    the status was last written can go with their photographs before the run
    gets to them, and a listing whose remaining jobs have all gone must not be
    left saying "processing".
    """
    add_photographs(sessions, 1)
    queue_everything(sessions)
    monkeypatch.setattr(processing, "_processor", Pipeline())
    processing.run_listing_jobs(LISTING_ID)
    with sessions() as session:
        # As the status stands when it was written while a job was still to
        # come, and the job has since gone.
        session.get(VehicleListing, LISTING_ID).processing_status = "processing"
        session.commit()

    processing.run_listing_jobs(LISTING_ID)

    assert listing_status(sessions) == "complete"


# ── A fault around one job is that job's alone ────────────────────────────────

def test_an_error_between_jobs_does_not_stop_the_run(sessions, monkeypatch):
    """
    run_job keeps its own failures to itself, but the run does more than call
    it. Here the listing's status write is refused once — what SQLite does
    when its lock wait runs out — and that used to escape the loop, taking the
    photograph just finished back to "processing" with it and leaving every
    later one pending.
    """
    photographs = list(add_photographs(sessions, 3))
    queue_everything(sessions)
    monkeypatch.setattr(processing, "_processor", Pipeline())

    refresh = processing._refresh_listing_status
    refused = []

    def refused_once(session, listing_id):
        if not refused:
            refused.append(listing_id)
            raise OperationalError(
                "UPDATE vehicle_listings ...", None, Exception("database is locked")
            )
        refresh(session, listing_id)

    monkeypatch.setattr(processing, "_refresh_listing_status", refused_once)

    processing.run_listing_jobs(LISTING_ID)

    assert refused, "the fault was never injected"
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in photographs}
    assert listing_status(sessions) == "complete"


def test_a_job_that_breaks_outside_its_own_handling_stops_only_itself(sessions, monkeypatch):
    """
    run_job promises never to raise, and deals with whatever goes wrong in the
    models itself. Should that promise break — the database refusing the claim
    each time its lock wait runs out, say — the fault stays with the one job:
    the rest of the listing still goes through, and the broken job is left
    pending for the next press rather than tried again and again in a tight
    loop. Before, the first such fault ended the run with every later job
    pending.
    """
    photographs = list(add_photographs(sessions, 3))
    queue_everything(sessions)
    monkeypatch.setattr(processing, "_processor", Pipeline())

    run_job = processing.run_job

    def breaks_on_the_first_photograph(session, job):
        if job.input_image_id == photographs[0]:
            raise OperationalError(
                "UPDATE processing_jobs ...", None, Exception("database is locked")
            )
        run_job(session, job)

    monkeypatch.setattr(processing, "run_job", breaks_on_the_first_photograph)

    run = listing_run()
    run.start()
    run.finish()

    assert run.error is None
    assert history(sessions) == {
        photographs[0]: [("pending", None)],
        photographs[1]: [("completed", "ok")],
        photographs[2]: [("completed", "ok")],
    }


# ── Two runs, or two presses, over one listing ────────────────────────────────

def test_two_runs_over_one_listing_put_each_photograph_through_once(sessions, monkeypatch):
    """
    The defect this exists to catch. A second run started while one was going —
    pressing Process again starts one — picked up every pending job, including
    the ones the first run had lined up and not yet reached, and both ran them.
    Here the first, working from the list it took at the start, reaches jobs
    the second has already finished and starts them again: the start time lands
    after the finish, the completion_after_start check refuses the write, and
    the run ends there. Two runs inside the same photograph at once fare no
    better; the next test is that case.
    """
    contents = add_photographs(sessions, 3)
    queue_everything(sessions)
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    first = listing_run()
    first.start()
    try:
        assert pipeline.inside.wait(HANG_GUARD_S), "the first run never reached the models"
        second = listing_run()
        second.start()
        second.finish()
    finally:
        pipeline.go.set()
        first.finish()

    assert first.error is None and second.error is None
    assert {image_id: pipeline.calls[content] for image_id, content in contents.items()} == {
        image_id: 1 for image_id in contents
    }
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in contents}
    assert listing_status(sessions) == "complete"


def test_a_job_another_run_is_already_working_on_is_not_run_again(sessions, monkeypatch):
    """
    What stops that at the level of a single job, whichever run holds it. Two
    sessions load the same pending job. The first starts it and is in the
    models; the second's copy still says pending, and run_job used to take its
    word for it — marking the job started again and putting the photograph
    through a second time. Whichever finished second then collided with the
    other's output on images.storage_path and recorded the job as failed,
    though the photograph had been processed successfully.
    """
    contents = add_photographs(sessions, 1)
    (job_id,) = queue_everything(sessions)
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    with sessions() as first_session, sessions() as second_session:
        mine = first_session.get(ProcessingJob, job_id)
        theirs = second_session.get(ProcessingJob, job_id)

        def first_run():
            processing.run_job(first_session, mine)
            first_session.commit()

        first = InThread(first_run)
        first.start()
        try:
            assert pipeline.inside.wait(HANG_GUARD_S), "the first run never reached the models"
            processing.run_job(second_session, theirs)
            second_session.commit()
        finally:
            pipeline.go.set()
            first.finish()

    assert first.error is None
    (content,) = contents.values()
    assert pipeline.calls[content] == 1
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in contents}


def test_a_finished_job_is_not_started_again(sessions, monkeypatch):
    """
    The same stale copy, arriving after the job has finished. Marking it
    started again put a start time after the finish on the row, the
    completion_after_start check refused the write, and — that write sitting
    outside the job's error handling — run_job raised, which it promises never
    to do, and took down whichever run had called it.
    """
    contents = add_photographs(sessions, 1)
    (job_id,) = queue_everything(sessions)
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)

    with sessions() as first, sessions() as second:
        mine = first.get(ProcessingJob, job_id)
        theirs = second.get(ProcessingJob, job_id)

        processing.run_job(first, mine)
        first.commit()
        processing.run_job(second, theirs)
        second.commit()

    (content,) = contents.values()
    assert pipeline.calls[content] == 1
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in contents}


def test_a_second_run_leaves_the_listing_to_the_one_already_going(sessions, monkeypatch):
    """
    Every press of Process schedules a run, so a listing can be handed a second
    one while its first is still going. The second steps aside rather than
    working through the same queue alongside it. Two runs splitting a listing
    each write its status from what they last saw, and the later write is not
    always the fresher one — the listing could be left saying "processing"
    after both had finished — and they would put two of the dealer's
    photographs through the models at once, for no gain.
    """
    contents = add_photographs(sessions, 3)
    queue_everything(sessions)
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    first = listing_run()
    first.start()
    try:
        assert pipeline.inside.wait(HANG_GUARD_S), "the first run never reached the models"
        second = listing_run()
        second.start()
        second.finish()
        sent_while_the_first_was_going = sum(pipeline.calls.values())
    finally:
        pipeline.go.set()
        first.finish()

    assert second.error is None
    assert sent_while_the_first_was_going == 1, "only the photograph the first run holds"
    assert first.error is None
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in contents}


def test_a_press_landing_as_a_run_finishes_is_not_lost(sessions, monkeypatch):
    """
    The one gap stepping aside leaves open. A press can land after the run
    already going has looked and found nothing left, but before it has stood
    down: the press's own run sees it still registered and leaves the new job
    to it. The run looks once more after standing down, so that job is picked
    up rather than left pending with no run to take it.

    The press is made to land in exactly that gap by having it happen during
    the run's last status roll-up — the step between its final look and
    standing down.
    """
    photographs = list(add_photographs(sessions, 1))
    queue_everything(sessions)
    monkeypatch.setattr(processing, "_processor", Pipeline())

    roll_up = processing._roll_up
    roll_ups = []
    added = {}

    def press_during_the_last_roll_up(factory, listing_id):
        roll_up(factory, listing_id)
        roll_ups.append(listing_id)
        # One after the only job, then the last one, once nothing is left.
        if len(roll_ups) == 2:
            added.update(add_photographs(sessions, 1, first=1))
            _, background = press_process(sessions)
            run_scheduled(background)

    monkeypatch.setattr(processing, "_roll_up", press_during_the_last_roll_up)

    processing.run_listing_jobs(LISTING_ID)

    assert added, "the press never landed"
    assert history(sessions) == {
        image_id: [("completed", "ok")] for image_id in [*photographs, *added]
    }
    assert listing_status(sessions) == "complete"


def test_pressing_process_during_a_run_reports_the_run_and_queues_nothing_new(
    sessions, monkeypatch
):
    """
    The defect this exists to catch. create_jobs skipped only photographs that
    had already succeeded, so a second press queued every other one again —
    the one in the models included — for a second run to take. A photograph
    whose job is in flight is now left to it, and with nothing new queued the
    endpoint answers with the run's progress: the old 400, "every photograph is
    already done", would be untrue while the run is still working on them.
    """
    photographs = list(add_photographs(sessions, 3))
    pipeline = Pipeline(hold_first=True)
    monkeypatch.setattr(processing, "_processor", pipeline)

    queued, background = press_process(sessions)
    assert queued.total == 3

    run = InThread(lambda: run_scheduled(background))
    run.start()
    try:
        assert pipeline.inside.wait(HANG_GUARD_S), "the run never reached the models"
        again, _ = press_process(sessions)
    finally:
        pipeline.go.set()
        run.finish()

    assert again.processing_status == "processing"
    assert {job.input_image_id: job.status for job in again.jobs} == {
        photographs[0]: "processing",
        photographs[1]: "pending",
        photographs[2]: "pending",
    }
    assert run.error is None
    assert history(sessions) == {image_id: [("completed", "ok")] for image_id in photographs}


# ── A listing a stopped server left half-done ─────────────────────────────────

def test_a_job_left_processing_by_a_stopped_server_does_not_block_a_new_run(
    sessions, monkeypatch
):
    """
    A job that was in the models when the server stopped says "processing"
    until something closes it: the full application's startup recovery
    (processing.recover_interrupted_jobs) does, and so must pressing Process,
    since the light API never runs that recovery. Leaving in-flight
    photographs alone must not include that one: no run in this process is
    working on it, and it will never finish. It is closed off as failed, so it
    stops reading as in progress, and the photograph is queued afresh.
    """
    contents = add_photographs(sessions, 1)
    (image_id,) = contents
    add_job(
        sessions,
        image_id,
        status="processing",
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)

    _, background = press_process(sessions)
    run_scheduled(background)

    assert pipeline.calls[contents[image_id]] == 1
    assert history(sessions) == {image_id: [("failed", None), ("completed", "ok")]}
    assert listing_status(sessions) == "complete"


def test_a_job_left_pending_by_a_stopped_server_is_run_once_by_the_next_press(
    sessions, monkeypatch
):
    """
    A job queued just before the server stopped is pending with no run left to
    take it. The next press has to start one even though it queues nothing new
    — the photograph already has its job — and that job has to run exactly
    once. Before, the press queued the photograph a second time, and the run it
    started processed both.
    """
    contents = add_photographs(sessions, 1)
    (image_id,) = contents
    add_job(sessions, image_id, status="pending")
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)

    _, background = press_process(sessions)
    run_scheduled(background)

    assert pipeline.calls[contents[image_id]] == 1
    assert history(sessions) == {image_id: [("completed", "ok")]}
    assert listing_status(sessions) == "complete"
