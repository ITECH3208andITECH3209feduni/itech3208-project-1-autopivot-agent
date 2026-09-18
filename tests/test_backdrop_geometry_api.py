# Tests for storing a backdrop's measured geometry and correcting it by hand.
#
# The schema is built on in-memory SQLite with foreign keys enforced, the same
# way tests/test_image_lineage.py does it, so none of this needs PostgreSQL:
#
#     pytest tests/test_backdrop_geometry_api.py -v

import io

import pytest
from fastapi import HTTPException
from PIL import Image as PilImage, ImageDraw
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import backdrop_analysis
from api import routes_backdrops
from api.schemas import BackdropGeometryIn
from database.base import Base
from database.models import Backdrop, Dealership, User


# SQLite only auto-assigns a primary key for a column declared exactly INTEGER
# PRIMARY KEY, and every key in this schema is BigInteger, which is right for
# PostgreSQL. This narrows the SQLite DDL only.
@compiles(BigInteger, "sqlite")
def _bigint_is_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


DEALERSHIP_ID = 1
OTHER_DEALERSHIP_ID = 2


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for dealership_id, name in (
            (DEALERSHIP_ID, "Ours"), (OTHER_DEALERSHIP_ID, "Theirs")
        ):
            session.add(Dealership(id=dealership_id, name=name))
        session.add(
            User(
                id=1,
                dealership_id=DEALERSHIP_ID,
                email="dealer@example.com",
                password_hash="x",
                first_name="A",
                last_name="Dealer",
                role="dealership_admin",
            )
        )
        session.flush()
        yield session


def backdrop_row(session, dealership_id=DEALERSHIP_ID, name="Showroom"):
    row = Backdrop(
        dealership_id=dealership_id,
        name=name,
        storage_path=f"{dealership_id}/{name}.png",
        mime_type="image/png",
        suits_angles=[],
    )
    session.add(row)
    session.flush()
    return row


def room_bytes(vanishing_y=400, size=(1200, 900)):
    """A drawn room whose lines converge, encoded as a dealer's upload would be."""
    canvas = PilImage.new("RGB", size, (200, 200, 205))
    draw = ImageDraw.Draw(canvas)
    width, height = size
    for corner in (
        (0, 0), (width, 0), (0, height), (width, height),
        (0, height * 0.45), (width, height * 0.45),
    ):
        draw.line([corner, (600, vanishing_y)], fill=(20, 20, 25), width=5)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


# ── Measuring on upload ────────────────────────────────────────────────────────

def test_an_uploaded_backdrop_is_measured(session):
    """
    The measurement happens once, when the backdrop is added, because it is a
    property of the backdrop rather than of any job. Measuring per job would
    repeat identical work for every photograph in every listing that uses it.
    """
    geometry = routes_backdrops._measure(room_bytes(vanishing_y=400))
    assert geometry is not None

    row = backdrop_row(session)
    routes_backdrops._apply_geometry(row, geometry)
    session.flush()

    assert float(row.horizon_y_ratio) == pytest.approx(400 / 900, abs=0.02)
    assert row.horizon_method == "vanishing_point"
    assert float(row.horizon_confidence) > 0.5
    assert float(row.floor_top_y_ratio) > 0


def test_an_unreadable_upload_does_not_fail_the_upload(session):
    """
    The defect this exists to catch. A dealer adding a showroom photograph is
    adding a backdrop, not requesting a measurement, so an image the analyser
    cannot read has to leave the columns null and let the upload succeed.
    """
    assert routes_backdrops._measure(b"this is not an image") is None


def test_a_backdrop_that_was_never_measured_is_distinguishable(session):
    """
    Null means never looked at; method 'assumed' with a zero confidence means
    looked at and found unreadable. The compositor treats those differently, so
    they must not collapse into one another.
    """
    never_measured = backdrop_row(session, name="Old")
    assert never_measured.horizon_y_ratio is None
    assert never_measured.horizon_method is None

    seamless = routes_backdrops._measure(
        _png(PilImage.new("RGB", (800, 600), (245, 245, 245)))
    )
    assert seamless is not None
    assert seamless.horizon_method == "assumed"
    assert seamless.horizon_confidence == 0.0


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ── Correcting it by hand ──────────────────────────────────────────────────────

def test_a_dealer_can_correct_the_measurement(session):
    """
    A seamless backdrop gives the analyser nothing to work from, and saying so
    honestly is only useful if the person who took the photograph can then put
    it right.
    """
    row = backdrop_row(session)
    routes_backdrops._apply_geometry(
        row, routes_backdrops._measure(_png(PilImage.new("RGB", (800, 600), (245,) * 3)))
    )
    session.flush()

    result = routes_backdrops.set_backdrop_geometry(
        row.id,
        session.get(User, 1),
        session,
        BackdropGeometryIn(horizon_y_ratio=0.42, floor_top_y_ratio=0.71),
    )

    assert result.horizon_y_ratio == pytest.approx(0.42)
    assert result.floor_top_y_ratio == pytest.approx(0.71)
    assert result.geometry_overridden is True
    assert result.horizon_confidence == pytest.approx(1.0), (
        "a person looking at their own showroom is the strongest evidence there is"
    )


def test_a_correction_cannot_reach_another_dealerships_backdrop(session):
    """Every backdrop route is scoped to the caller's dealership."""
    theirs = backdrop_row(session, dealership_id=OTHER_DEALERSHIP_ID, name="Theirs")

    with pytest.raises(HTTPException) as raised:
        routes_backdrops.set_backdrop_geometry(
            theirs.id,
            session.get(User, 1),
            session,
            BackdropGeometryIn(horizon_y_ratio=0.5, floor_top_y_ratio=0.8),
        )

    assert raised.value.status_code == 404


def test_the_measurement_is_reported_to_the_client(session):
    """
    A dealer cannot correct a number they are never shown, and the confidence is
    what tells them whether it is worth looking at.
    """
    row = backdrop_row(session)
    routes_backdrops._apply_geometry(row, routes_backdrops._measure(room_bytes()))
    session.flush()

    reported = routes_backdrops._serialise(row)

    assert reported.horizon_y_ratio is not None
    assert reported.horizon_method in backdrop_analysis.HORIZON_METHODS
    assert reported.floor_top_y_ratio is not None
    assert reported.geometry_overridden is False
