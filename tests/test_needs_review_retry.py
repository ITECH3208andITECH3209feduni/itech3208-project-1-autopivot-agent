import itertools

from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
import pytest

from api import processing
from database.base import Base
from database.models import Dealership, Image, ProcessingJob, User, VehicleListing


@compiles(BigInteger, "sqlite")
def _bigint_is_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


DEALERSHIP_ID = 1
LISTING_ID = 1

_storage_paths = itertools.count()


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as opened:
        opened.add(Dealership(id=DEALERSHIP_ID, name="Bayside Motors", status="active"))
        opened.add(
            User(
                id=1,
                dealership_id=DEALERSHIP_ID,
                email="dana@bayside.test",
                password_hash="x",
                first_name="Dana",
                last_name="Reid",
                role="dealership_admin",
            )
        )
        listing = VehicleListing(
            id=LISTING_ID,
            dealership_id=DEALERSHIP_ID,
            created_by_user_id=1,
            title="2021 Mazda CX-5",
            make="Mazda",
            model="CX-5",
            year=2021,
            status="draft",
            processing_status="needs_review",
        )
        opened.add(listing)
        opened.commit()
        yield opened


def add_original(session):
    image = Image(
        vehicle_listing_id=LISTING_ID,
        image_type="original",
        original_filename="front.jpg",
        storage_path=f"{DEALERSHIP_ID}/original/{next(_storage_paths)}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=1024,
        width=1600,
        height=1200,
    )
    session.add(image)
    session.flush()
    return image


def add_processed(session, original):
    """The composite a successful run leaves behind, linked to its original."""
    output = Image(
        vehicle_listing_id=LISTING_ID,
        image_type="processed",
        source_image_id=original.id,
        original_filename=original.original_filename,
        storage_path=f"{DEALERSHIP_ID}/processed/{next(_storage_paths)}.png",
        mime_type="image/png",
        file_size_bytes=1024,
        width=1600,
        height=1200,
    )
    session.add(output)
    session.flush()
    return output


def add_job(session, image, status, review_state, output=None):
    job = ProcessingJob(
        vehicle_listing_id=LISTING_ID,
        dealership_id=DEALERSHIP_ID,
        input_image_id=image.id,
        output_image_id=output.id if output is not None else None,
        processing_type="full_pipeline",
        status=status,
        review_state=review_state,
    )
    session.add(job)
    session.commit()
    return job


def test_a_needs_review_photograph_is_queued_again_by_reprocess(session):
    """The defect this exists to catch: `run_job` records a "no vehicle detected"
    outcome as status "completed" (the run itself did not fail), with review_state
    "needs_review" marking it for a person.
    """
    image = add_original(session)
    add_job(session, image, status="completed", review_state="needs_review")

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert [j.input_image_id for j in queued] == [image.id]
    assert queued[0].status == "pending"


def test_a_successfully_processed_photograph_is_not_queued_again(session):
    """Unchanged behaviour: real success is still skipped, so Reprocess does not
    duplicate work that already produced a usable result.
    """
    image = add_original(session)
    add_job(
        session, image, status="completed", review_state="ok",
        output=add_processed(session, image),
    )

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert queued == []


def test_a_failed_photograph_is_still_queued_again(session):
    """Unchanged behaviour, checked directly: a crashed job was never status ==
    "completed", so it was never in scope for this fix.
    """
    image = add_original(session)
    add_job(session, image, status="failed", review_state=None)

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert [j.input_image_id for j in queued] == [image.id]


# ── Queue: no duplicates, one at a time, survives a restart ──────────────────

def test_only_one_photograph_is_in_the_models_at_a_time(monkeypatch):
    """Each listing has its own run, so eight vehicles used to mean eight photographs
    fighting over one CPU. PROCESSING_WORKERS caps it across all.
    """
    import threading
    import time
    from contextlib import nullcontext
    from types import SimpleNamespace

    fake_session = SimpleNamespace(
        get=lambda model, job_id: SimpleNamespace(id=job_id), commit=lambda: None,
    )
    factory = lambda: nullcontext(fake_session)  # noqa: E731
    busy, most = [0], [0]
    lock = threading.Lock()

    def slow_job(session, job):
        with lock:
            busy[0] += 1
            most[0] = max(most[0], busy[0])
        time.sleep(0.2)
        with lock:
            busy[0] -= 1

    monkeypatch.setattr(processing, "run_job", slow_job)
    monkeypatch.setattr(processing, "_workers", threading.BoundedSemaphore(1))
    runners = [threading.Thread(target=processing._run_one, args=(factory, job_id))
               for job_id in (101, 102)]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join()
    assert most[0] == 1

