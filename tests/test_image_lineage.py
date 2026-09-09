# Tests for images.source_image_id — the link from a processed photograph back
# to the original it was made from.
#
# The schema is built on in-memory SQLite with foreign key enforcement switched
# on, so none of this needs PostgreSQL:
#
#     pytest tests/test_image_lineage.py -v
#
# SQLite is not the production database, but it does enforce composite foreign
# keys and ON DELETE RESTRICT, which is the whole of what is under test here.

import io
import itertools

import pytest
from PIL import Image as PilImage
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from api import processing, routes_listings, storage
from database.base import Base
from database.models import Dealership, Image, ProcessingJob, User, VehicleListing


# SQLite assigns a primary key only for a column declared exactly INTEGER
# PRIMARY KEY, and every key in this schema is BigInteger, which is the right
# choice for PostgreSQL. Without this narrowing the rows the application creates
# for itself could not be inserted here at all — a processed image never picks
# its own id — and the pipeline test below would be reduced to asserting
# something it had set up by hand. It rewrites the SQLite DDL only.
@compiles(BigInteger, "sqlite")
def _bigint_is_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


DEALERSHIP_ID = 1
LISTING_ID = 1

_storage_paths = itertools.count()


@pytest.fixture
def session(tmp_path, monkeypatch):
    """One dealership, one user, one listing, and nowhere real to write."""
    # The deletion routes remove files once their rows are gone. Pointing the
    # storage root at a temporary directory means a test can never reach a file
    # a developer actually cares about.
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path.resolve())

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, record):
        # SQLite ignores every foreign key unless each connection asks for
        # them, and a test that has quietly stopped checking constraints passes
        # whatever it is given.
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
        opened.add(
            VehicleListing(
                id=LISTING_ID,
                dealership_id=DEALERSHIP_ID,
                created_by_user_id=1,
                title="2021 Mazda CX-5",
                make="Mazda",
                model="CX-5",
                year=2021,
                status="draft",
                processing_status="pending",
            )
        )
        opened.commit()
        yield opened


def add_image(session, image_type="original", source_image_id=None, listing_id=LISTING_ID):
    image = Image(
        vehicle_listing_id=listing_id,
        image_type=image_type,
        source_image_id=source_image_id,
        original_filename="front.jpg",
        storage_path=f"{DEALERSHIP_ID}/{image_type}/{next(_storage_paths)}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=1024,
        width=1600,
        height=1200,
    )
    session.add(image)
    session.flush()
    return image


def processed_photograph(session):
    """An original, the composite made from it, and the job that did it."""
    original = add_image(session)
    processed = add_image(session, image_type="processed", source_image_id=original.id)
    job = ProcessingJob(
        vehicle_listing_id=LISTING_ID,
        dealership_id=DEALERSHIP_ID,
        input_image_id=original.id,
        output_image_id=processed.id,
        processing_type="full_pipeline",
        status="completed",
        review_state="ok",
    )
    session.add(job)
    session.commit()
    return original, processed, job


def constraint(name):
    for candidate in Image.__table__.constraints:
        if candidate.name == name:
            return candidate
    raise AssertionError(f"images carries no constraint named {name!r}")


def png_bytes(colour=(20, 40, 90)):
    buffer = io.BytesIO()
    PilImage.new("RGB", (32, 24), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class StubProcessor:
    """Stands in for the vision stack: one fixed image, no model, no GPU."""

    def __init__(self, image_png):
        self._image_png = image_png

    def process(
        self,
        image: bytes,
        background: bytes | None,
        placement: processing.BackdropPlacement | None = None,
    ):
        return processing.ProcessOutcome(
            image_png=self._image_png, vehicle_detected=True, model_used="stub"
        )


# ── The constraint itself ─────────────────────────────────────────────────────

def test_the_source_link_is_a_listing_scoped_pair():
    """
    Handover gap 4 is that a processed image cannot be traced to its original.
    The pair form is what keeps the trace inside one tenant: a plain reference
    to images.id would let a derived row name a photograph belonging to another
    dealership's listing, which is the leak every other composite key here
    exists to prevent.
    """
    pair = constraint("source_image_same_listing")

    assert [column.name for column in pair.columns] == [
        "source_image_id",
        "vehicle_listing_id",
    ]
    assert [(e.column.table.name, e.column.name) for e in pair.elements] == [
        ("images", "id"),
        ("images", "vehicle_listing_id"),
    ]


def test_the_source_link_restricts_on_delete():
    """
    RESTRICT, matching every neighbouring constraint. CASCADE would take the
    composite away with its original unasked, and SET NULL would leave an
    "after" that can no longer be shown beside anything — both discard the
    before-and-after pair the realism work is measured on, and neither says so.
    """
    assert constraint("source_image_same_listing").ondelete == "RESTRICT"


def test_the_referenced_pair_is_backed_by_a_unique_constraint():
    """
    A composite foreign key needs a unique index over exactly the columns it
    names. Without image_listing_pair, PostgreSQL rejects the constraint as it
    is created, so the migration fails on a clean database rather than the
    schema quietly coming up without the rule.
    """
    assert [column.name for column in constraint("image_listing_pair").columns] == [
        "id",
        "vehicle_listing_id",
    ]


def test_source_image_id_is_nullable():
    """
    An original has no source, and neither has anything processed before the
    column existed — the job that produced it is long gone, so the pairing
    cannot be backfilled. NOT NULL would have made the migration unrunnable on
    any database with rows in it.
    """
    assert Image.__table__.c.source_image_id.nullable


# ── What the database refuses ─────────────────────────────────────────────────

def test_a_source_in_another_listing_is_refused(session):
    """The point of the pair: lineage cannot be made to cross a listing."""
    original = add_image(session)
    session.add(
        VehicleListing(
            id=2,
            dealership_id=DEALERSHIP_ID,
            created_by_user_id=1,
            title="2019 Toyota Hilux",
            make="Toyota",
            model="Hilux",
            year=2019,
            status="draft",
            processing_status="pending",
        )
    )
    session.commit()

    with pytest.raises(IntegrityError):
        add_image(session, image_type="processed", source_image_id=original.id, listing_id=2)
    session.rollback()


def test_an_image_cannot_be_its_own_source(session):
    """
    A row naming itself could never be deleted: RESTRICT is checked against the
    row being removed as well, so its own reference would refuse the delete and
    the dealer would be left with a photograph that cannot be got rid of.
    """
    image = add_image(session)
    image.source_image_id = image.id

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── The pipeline records it ───────────────────────────────────────────────────

def test_a_finished_job_records_which_original_its_output_came_from(session, monkeypatch):
    """
    Handover gap 4 at the point where it is created. The pipeline wrote the
    processed image with nothing on it naming its input, so the only route back
    was the job — and a job is deleted along with the photograph it consumed,
    so the pairing disappeared at the first tidy-up.
    """
    source_png = png_bytes()
    stored = storage.save_image(DEALERSHIP_ID, "original", source_png)
    original = Image(
        vehicle_listing_id=LISTING_ID,
        image_type="original",
        original_filename="front.png",
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size_bytes=stored.size_bytes,
        width=stored.width,
        height=stored.height,
    )
    session.add(original)
    session.flush()

    job = ProcessingJob(
        vehicle_listing_id=LISTING_ID,
        dealership_id=DEALERSHIP_ID,
        input_image_id=original.id,
        processing_type="full_pipeline",
        status="pending",
    )
    session.add(job)
    session.flush()

    monkeypatch.setattr(processing, "_processor", StubProcessor(png_bytes((200, 30, 30))))
    processing.run_job(session, job)

    assert job.status == "completed", job.error_message
    output = session.get(Image, job.output_image_id)
    assert output.image_type == "processed"
    assert output.source_image_id == original.id


# ── Deletion, which the new reference is in the way of ────────────────────────

def test_a_photograph_can_still_be_deleted_after_it_has_been_processed(session):
    """
    The defect this exists to catch. source_image_id adds a RESTRICT reference
    from the composite back to the original, so the original's delete is
    refused while the composite is still there. Unhandled, a dealer could not
    remove a photograph once it had been through the pipeline — which is
    exactly when they want to, because an advertisement banner pulled in by a
    URL import is only recognisable as junk after it has been processed.
    """
    original, processed, job = processed_photograph(session)
    original_id, processed_id, job_id = original.id, processed.id, job.id

    routes_listings.delete_image(LISTING_ID, original_id, session.get(User, 1), session)

    assert session.get(Image, original_id) is None
    assert session.get(Image, processed_id) is None, "the composite goes with its original"
    assert session.get(ProcessingJob, job_id) is None


def test_a_listing_can_still_be_deleted_after_it_has_been_processed(session):
    """
    The same reference, reached by the other route. delete_listing removes
    every photograph in one flush, so whichever order the session happens to
    emit them in decides the outcome: an original emitted before the composite
    made from it is refused, and the dealer is told a listing they are looking
    at cannot be deleted.
    """
    processed_photograph(session)

    routes_listings.delete_listing(LISTING_ID, session.get(User, 1), session)

    assert session.scalars(select(Image)).all() == []
    assert session.get(VehicleListing, LISTING_ID) is None


def test_deleting_a_composite_leaves_its_original_and_the_job(session):
    """Unchanged behaviour: the photograph can simply be processed again."""
    original, processed, job = processed_photograph(session)
    original_id, processed_id, job_id = original.id, processed.id, job.id

    routes_listings.delete_image(LISTING_ID, processed_id, session.get(User, 1), session)

    assert session.get(Image, original_id) is not None
    assert session.get(Image, processed_id) is None
    reloaded = session.get(ProcessingJob, job_id)
    assert reloaded is not None and reloaded.output_image_id is None


def test_a_composite_is_found_by_its_source_link_not_only_through_its_job(session):
    """
    _release_job_references finds derived images through the job's output
    pointer, which is a second copy of the same fact — and one the function
    itself sets to NULL a few lines earlier. The database enforces RESTRICT on
    images.source_image_id, so with the job pointer already cleared, following
    it alone leaves the composite in place and the original's delete is
    refused.
    """
    original, processed, job = processed_photograph(session)
    original_id, processed_id = original.id, processed.id
    processed_path = processed.storage_path
    job.output_image_id = None
    session.commit()

    released = routes_listings._release_job_references(session, {original_id})

    assert processed_path in released, "the file has to be removed as well as the row"
    assert session.get(Image, processed_id) is None


# ── What the API says about it ────────────────────────────────────────────────

def test_the_api_reports_which_original_a_processed_image_came_from(session):
    """A before/after pair is buildable from the listing alone, without also
    fetching its jobs."""
    original, processed, _ = processed_photograph(session)

    assert routes_listings._serialise_image(processed).source_image_id == original.id
    assert routes_listings._serialise_image(original).source_image_id is None
