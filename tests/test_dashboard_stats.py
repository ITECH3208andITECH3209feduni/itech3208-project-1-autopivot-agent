"""BUG 4 — the dashboard's "Images processed" counts uploaded originals.

`dashboard_stats` computes `images_processed` as the all-time count of
`Image.image_type == "original"` for the dealership. The schema documents
`DashboardStats` as scoped to the current month (see the `NavCounts` docstring),
and the tile is labelled "Images processed", so it should count *processed*
images created in the current month, using the same month boundary as
`vehicles_this_month`.

In-memory SQLite, as tests/test_image_lineage.py builds it:

    pytest tests/test_dashboard_stats.py -v
"""

import itertools
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from api import routes_dashboard
from database.base import Base
from database.models import Dealership, Image, User, VehicleListing

DEALERSHIP_ID = 1
OTHER_DEALERSHIP_ID = 2

_paths = itertools.count()


@compiles(BigInteger, "sqlite")
def _bigint_is_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for did, name in ((DEALERSHIP_ID, "Ours"), (OTHER_DEALERSHIP_ID, "Theirs")):
            session.add(Dealership(id=did, name=name, status="active"))
        session.flush()
        for uid, did in ((1, DEALERSHIP_ID), (2, OTHER_DEALERSHIP_ID)):
            session.add(
                User(
                    id=uid,
                    dealership_id=did,
                    email=f"dealer{uid}@example.com",
                    password_hash="x",
                    first_name="A",
                    last_name="Dealer",
                    role="dealership_admin",
                )
            )
        session.flush()
        for did, lid, uid in ((DEALERSHIP_ID, 1, 1), (OTHER_DEALERSHIP_ID, 2, 2)):
            session.add(
                VehicleListing(
                    id=lid,
                    dealership_id=did,
                    created_by_user_id=uid,
                    title="Car",
                    make="Mazda",
                    model="CX-5",
                    year=2021,
                    status="draft",
                    processing_status="pending",
                )
            )
        session.flush()
        yield session


def _image(session, listing_id, image_type, created_at):
    session.add(
        Image(
            vehicle_listing_id=listing_id,
            image_type=image_type,
            original_filename="p.jpg",
            storage_path=f"x/{image_type}/{next(_paths)}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=1024,
            width=100,
            height=80,
            created_at=created_at,
        )
    )


def test_images_processed_counts_processed_this_month_for_this_dealership(session):
    now = datetime.now(timezone.utc)
    this_month = now
    last_month = _month_start(now) - timedelta(seconds=1)

    # Should count: processed, this month, dealership 1.
    _image(session, 1, "processed", this_month)
    _image(session, 1, "processed", this_month)
    # Excluded: an uploaded original this month.
    _image(session, 1, "original", this_month)
    # Excluded: processed but last month.
    _image(session, 1, "processed", last_month)
    # Excluded: processed this month but another dealership's listing.
    _image(session, 2, "processed", this_month)
    session.commit()

    stats = routes_dashboard.dashboard_stats(session.get(User, 1), session)

    assert stats.images_processed == 2, (
        "Images processed must count processed images from this month only, "
        "scoped to the dealership — not uploaded originals or old/other rows"
    )


def test_images_processed_is_zero_when_only_originals_exist(session):
    now = datetime.now(timezone.utc)
    _image(session, 1, "original", now)
    _image(session, 1, "original", now)
    session.commit()

    stats = routes_dashboard.dashboard_stats(session.get(User, 1), session)
    assert stats.images_processed == 0
