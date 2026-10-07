# Tests for processing a photograph again after its composite was deleted.
#
# Deleting a processed image on its own leaves the job that made it in place,
# pointing at nothing, "so the photograph can simply be processed again"
# (routes_listings._release_job_references). But create_jobs counted every job
# that had completed cleanly as done, output or no output, so pressing Process
# answered 400 — "every photograph is already done" — and the photograph could
# never get a composite back short of being deleted and uploaded afresh.
#
#     pytest tests/test_reprocess_deleted_output.py -v
#
# The database is a real SQLite file opened through database.connection's own
# get_engine, as in tests/test_processing_reliability.py, because the run a
# press starts takes sessions of its own.

import io

import pytest
from fastapi import BackgroundTasks
from PIL import Image as PilImage
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api import processing, routes_listings, storage
from api.schemas import ProcessRequest
from database import connection
from database.base import Base
from database.models import Dealership, Image, ProcessingJob, User, VehicleListing

DEALERSHIP_ID = 1
LISTING_ID = 1
USER_ID = 1


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


def add_image(session, image_type="original", source_image_id=None, colour=(20, 40, 90)):
    stored = storage.save_image(DEALERSHIP_ID, image_type, png_bytes(colour))
    image = Image(
        vehicle_listing_id=LISTING_ID,
        image_type=image_type,
        source_image_id=source_image_id,
        original_filename="front.png",
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size_bytes=stored.size_bytes,
        width=stored.width,
        height=stored.height,
    )
    session.add(image)
    session.flush()
    return image


def add_finished_job(session, original, output=None):
    """A job that completed cleanly — with its composite, or with none left."""
    job = ProcessingJob(
        vehicle_listing_id=LISTING_ID,
        dealership_id=DEALERSHIP_ID,
        input_image_id=original.id,
        output_image_id=output.id if output is not None else None,
        processing_type="full_pipeline",
        status="completed",
        review_state="ok",
    )
    session.add(job)
    session.commit()
    return job


def press_process(factory):
    """POST /api/listings/{id}/process, called as the route function, and the
    run it schedules, carried out the way FastAPI would once the response went."""
    background = BackgroundTasks()
    with factory() as session:
        summary = routes_listings.process_listing(
            LISTING_ID, ProcessRequest(), session.get(User, USER_ID), session, background
        )
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)
    return summary


class Pipeline:
    """Stands in for the vision stack: no model, no GPU, one fixed composite."""

    def __init__(self):
        self.calls = 0

    def process(self, image, background, placement=None):
        self.calls += 1
        return processing.ProcessOutcome(
            image_png=png_bytes((200, 30, 30)), vehicle_detected=True, model_used="stub"
        )


def composites_of(factory, original_id):
    with factory() as session:
        return session.scalars(
            select(Image.id).where(
                Image.image_type == "processed", Image.source_image_id == original_id
            )
        ).all()


def test_a_photograph_whose_composite_was_deleted_can_be_processed_again(
    sessions, monkeypatch
):
    """
    The defect itself, the way a dealer meets it: the composite comes back
    wrong, so they delete it and press Process for another go — and were told
    there was nothing to process.
    """
    with sessions() as session:
        original_id = add_image(session).id
        session.commit()
    pipeline = Pipeline()
    monkeypatch.setattr(processing, "_processor", pipeline)
    press_process(sessions)
    (composite_id,) = composites_of(sessions, original_id)

    with sessions() as session:
        routes_listings.delete_image(
            LISTING_ID, composite_id, session.get(User, USER_ID), session
        )
    summary = press_process(sessions)

    assert [(job.input_image_id, job.status) for job in summary.jobs] == [
        (original_id, "pending")
    ]
    assert pipeline.calls == 2
    assert len(composites_of(sessions, original_id)) == 1
    with sessions() as session:
        assert session.get(VehicleListing, LISTING_ID).processing_status == "complete"


def test_a_clean_finish_whose_output_is_gone_is_queued_again(sessions):
    """The same check where it is made. A job's history is kept when its output
    goes, so a job that completed cleanly is not, on its own, a photograph with
    a result."""
    with sessions() as session:
        original = add_image(session)
        add_finished_job(session, original)

        queued = processing.create_jobs(
            session, session.get(VehicleListing, LISTING_ID), backdrop=None
        )

        assert [job.input_image_id for job in queued] == [original.id]


def test_a_photograph_whose_composite_is_still_there_is_not_queued_again(sessions):
    """Unchanged behaviour: a real success, composite and all, is still
    skipped, so Process does not redo work that produced a usable result."""
    with sessions() as session:
        original = add_image(session)
        composite = add_image(
            session, image_type="processed", source_image_id=original.id, colour=(200, 30, 30)
        )
        add_finished_job(session, original, output=composite)

        queued = processing.create_jobs(
            session, session.get(VehicleListing, LISTING_ID), backdrop=None
        )

        assert queued == []
