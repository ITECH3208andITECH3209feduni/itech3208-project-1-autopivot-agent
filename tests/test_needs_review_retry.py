# Tests for create_jobs's "already done" check — specifically that a
# needs_review outcome (status "completed", review_state "needs_review") does
# not count as done, so pressing Reprocess can pick it up again.
#
#     pytest tests/test_needs_review_retry.py -v

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


def add_job(session, image, status, review_state):
    job = ProcessingJob(
        vehicle_listing_id=LISTING_ID,
        dealership_id=DEALERSHIP_ID,
        input_image_id=image.id,
        processing_type="full_pipeline",
        status=status,
        review_state=review_state,
    )
    session.add(job)
    session.commit()
    return job


def test_a_needs_review_photograph_is_queued_again_by_reprocess(session):
    """
    The defect this exists to catch: `run_job` records a "no vehicle
    detected" outcome as status "completed" (the run itself did not fail),
    with review_state "needs_review" marking it for a person. Before this
    fix, create_jobs treated any status == "completed" job as already done
    and silently skipped it forever — a dealer could delete the photograph
    and retake it, but pressing Reprocess could never try the same one again.
    """
    image = add_original(session)
    add_job(session, image, status="completed", review_state="needs_review")

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert [j.input_image_id for j in queued] == [image.id]
    assert queued[0].status == "pending"


def test_a_successfully_processed_photograph_is_not_queued_again(session):
    """Unchanged behaviour: real success is still skipped, so Reprocess does
    not duplicate work that already produced a usable result."""
    image = add_original(session)
    add_job(session, image, status="completed", review_state="ok")

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert queued == []


def test_a_failed_photograph_is_still_queued_again(session):
    """Unchanged behaviour, checked directly: a crashed job was never
    status == "completed", so it was never in scope for this fix."""
    image = add_original(session)
    add_job(session, image, status="failed", review_state=None)

    listing = session.get(VehicleListing, LISTING_ID)
    queued = processing.create_jobs(session, listing, backdrop=None)

    assert [j.input_image_id for j in queued] == [image.id]
