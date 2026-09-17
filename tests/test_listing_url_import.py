# Tests for the "already attached to a listing" bug in
# POST /api/listings/{id}/images/from-url.
#
# The reported symptom: importing photographs from a listing URL the dealer
# had never used before still failed with "Those photographs are already
# attached to a listing." Root cause — api/routes_listings.py,
# import_images_from_url: images.storage_path is content-addressed and
# globally unique per dealership (see database/models.py's Image and
# api/storage.py's docstring), and a scraped page brings in more than the
# vehicle photos — a site's own logo, a finance banner, a "sold" badge (see
# api/url_import.py's own notes on furniture it cannot filter out). The first
# listing to import a shared asset like that "claims" its storage_path
# forever; every later import of a *different, never-used* listing that also
# happens to scrape the same shared asset collided on that one file and — because
# the whole batch was added and committed together — failed the entire
# import, new vehicle photos included.
#
# The fix makes each photograph its own SAVEPOINT (session.begin_nested()),
# so one collision costs one photo rather than the request. These tests
# exercise the real route function against a throwaway SQLite database and a
# monkeypatched url_import.fetch_images — no network, no Postgres — which
# needs the SQLAlchemy/FastAPI stack but none of the ML environment:
#
#     pytest tests/test_listing_url_import.py -v

import asyncio
import io
import itertools

import pytest
from fastapi import HTTPException
from PIL import Image as PILImage
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.routes_listings as routes_listings
from api import storage, url_import
from api.schemas import UrlImportRequest
from database.base import Base
from database.models import Dealership, Image, User, VehicleListing


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    """
    A throwaway SQLite database with just the tables this route touches.
    ARRAY(Text).with_variant(JSON(), "sqlite") elsewhere in the schema is
    exactly this codebase anticipating a SQLite test path, but building only
    the four tables this route needs sidesteps every other model's own
    Postgres-only column types rather than relying on that variant everywhere.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Dealership.__table__, User.__table__,
            VehicleListing.__table__, Image.__table__,
        ],
    )
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    # The route itself never sets Image.id — on the real Postgres schema the
    # column is backed by a sequence the migration creates, which
    # Base.metadata.create_all (model definitions only, no migration DDL)
    # does not reproduce. Starting well above the small, explicit ids the
    # fixtures below assign avoids the two ever colliding.
    auto_ids = itertools.count(10_000)

    def _assign_id_if_missing(mapper, connection, target):
        if target.id is None:
            target.id = next(auto_ids)

    for model in (Dealership, User, VehicleListing, Image):
        event.listen(model, "before_insert", _assign_id_if_missing)

    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        for model in (Dealership, User, VehicleListing, Image):
            event.remove(model, "before_insert", _assign_id_if_missing)


@pytest.fixture()
def listing(db_session):
    # SQLite only aliases a bare "INTEGER PRIMARY KEY" column to its own
    # autoincrementing rowid; these models declare BigInteger primary keys
    # (correct for the real Postgres schema), which SQLite's dialect will not
    # auto-populate the same way — so ids are assigned explicitly here rather
    # than relying on autoincrement.
    dealership = Dealership(id=1, name="Test Motors")
    db_session.add(dealership)
    db_session.flush()

    user = User(
        id=1,
        dealership_id=dealership.id,
        email="dealer@example.test",
        password_hash="x",
        first_name="Test",
        last_name="Dealer",
        role="dealership_admin",
    )
    db_session.add(user)
    db_session.flush()

    vehicle = VehicleListing(
        id=1,
        dealership_id=dealership.id,
        created_by_user_id=user.id,
        title="2021 Toyota Corolla",
        make="Toyota",
        model="Corolla",
        year=2021,
    )
    db_session.add(vehicle)
    db_session.commit()
    return vehicle, user


def png_bytes(colour: tuple[int, int, int]) -> bytes:
    """A tiny, valid, distinguishable PNG — save_image's real inspect_image
    (PIL open + verify) runs against this, not a mock."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (220, 220), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def fetched(name: str, content: bytes) -> url_import.FetchedImage:
    return url_import.FetchedImage(filename=name, content_type="image/png", content=content)


def run_import(listing_id, user, session, url="https://dealer-site.test/listing/1"):
    return asyncio.run(
        routes_listings.import_images_from_url(
            listing_id, UrlImportRequest(url=url), user, session,
        )
    )


# ── The reported bug ─────────────────────────────────────────────────────────

def test_a_shared_site_asset_already_claimed_elsewhere_no_longer_fails_the_whole_import(
    db_session, listing, monkeypatch,
):
    """
    The core regression: dealership already has some *other* listing's import
    holding a shared site logo. A brand-new listing's brand-new URL scrapes
    that same logo alongside two genuine, never-before-seen vehicle photos.
    Only the logo should be left out — not the whole import.
    """
    vehicle, user = listing
    shared_logo = png_bytes((10, 10, 10))

    # Simulate: some earlier, unrelated listing already imported this exact
    # site asset.
    other_vehicle = VehicleListing(
        id=2,
        dealership_id=vehicle.dealership_id,
        created_by_user_id=user.id,
        title="2019 Mazda CX-5",
        make="Mazda",
        model="CX-5",
        year=2019,
    )
    db_session.add(other_vehicle)
    db_session.flush()
    stored_logo = storage.save_image(vehicle.dealership_id, "original", shared_logo)
    db_session.add(Image(
        id=1,
        vehicle_listing_id=other_vehicle.id,
        image_type="original",
        original_filename="site-logo.png",
        storage_path=stored_logo.storage_path,
        mime_type=stored_logo.mime_type,
        file_size_bytes=stored_logo.size_bytes,
        width=stored_logo.width,
        height=stored_logo.height,
    ))
    db_session.commit()

    async def fake_fetch_images(url):
        return url_import.ImportResult(images=[
            fetched("site-logo.png", shared_logo),          # collides
            fetched("front.jpg", png_bytes((200, 30, 30))),  # new
            fetched("rear.jpg", png_bytes((30, 200, 30))),   # new
        ])

    monkeypatch.setattr(url_import, "fetch_images", fake_fetch_images)

    result = run_import(vehicle.id, user, db_session)

    assert len(result.images) == 2, "the two genuine photos should still import"
    assert {i.original_filename for i in result.images} == {"front.jpg", "rear.jpg"}
    assert result.note is not None and "1 photograph" in result.note


def test_every_scraped_image_already_stored_gives_a_clear_message_not_a_conflict(
    db_session, listing, monkeypatch,
):
    """When literally everything scraped collides, the dealer is told why in
    plain language — this used to surface as a raw 409 "already attached"."""
    vehicle, user = listing
    duplicate = png_bytes((77, 77, 77))
    stored = storage.save_image(vehicle.dealership_id, "original", duplicate)
    db_session.add(Image(
        id=1,
        vehicle_listing_id=vehicle.id,
        image_type="original",
        original_filename="already-here.png",
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size_bytes=stored.size_bytes,
        width=stored.width,
        height=stored.height,
    ))
    db_session.commit()

    async def fake_fetch_images(url):
        return url_import.ImportResult(images=[fetched("same.png", duplicate)])

    monkeypatch.setattr(url_import, "fetch_images", fake_fetch_images)

    with pytest.raises(HTTPException) as exc_info:
        run_import(vehicle.id, user, db_session)

    assert exc_info.value.status_code == 422
    assert "already stored" in exc_info.value.detail


def test_an_import_with_no_duplicates_is_unaffected(db_session, listing, monkeypatch):
    vehicle, user = listing

    async def fake_fetch_images(url):
        return url_import.ImportResult(images=[
            fetched("front.jpg", png_bytes((1, 2, 3))),
            fetched("rear.jpg", png_bytes((4, 5, 6))),
        ])

    monkeypatch.setattr(url_import, "fetch_images", fake_fetch_images)

    result = run_import(vehicle.id, user, db_session)

    assert len(result.images) == 2
    assert result.note is None


def test_the_session_stays_usable_after_a_collision(db_session, listing, monkeypatch):
    """
    A savepoint that is not properly closed leaves the outer transaction
    unusable for anything after it — this is the failure mode a naive
    try/except session.add()/session.flush() without begin_nested() would hit.
    Proven here by successfully committing and re-querying afterwards.
    """
    vehicle, user = listing
    duplicate = png_bytes((9, 9, 9))
    stored = storage.save_image(vehicle.dealership_id, "original", duplicate)
    db_session.add(Image(
        id=1,
        vehicle_listing_id=vehicle.id,
        image_type="original",
        original_filename="dup.png",
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size_bytes=stored.size_bytes,
        width=stored.width,
        height=stored.height,
    ))
    db_session.commit()

    async def fake_fetch_images(url):
        return url_import.ImportResult(images=[
            fetched("dup.png", duplicate),
            fetched("new.jpg", png_bytes((50, 60, 70))),
        ])

    monkeypatch.setattr(url_import, "fetch_images", fake_fetch_images)
    run_import(vehicle.id, user, db_session)

    # The session must still be able to do ordinary work afterwards.
    count = db_session.query(Image).filter(
        Image.vehicle_listing_id == vehicle.id
    ).count()
    assert count == 2  # the pre-existing duplicate row + the one new import
