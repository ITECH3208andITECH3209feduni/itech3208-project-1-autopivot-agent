"""BUG 3 — deleting a backdrop can delete a file another backdrop still uses.

Backdrop files are content-addressed: `save_image` names them by the SHA-256 of
their bytes, and `backdrops.storage_path` is NOT unique, so the same image
uploaded under two names is one file on disk referenced by two rows.
`delete_backdrop` calls `storage.delete(path)` unconditionally, so deleting one
of the pair removes the file the other still points at.

In-memory SQLite, as tests/test_backdrop_geometry_api.py builds it:

    pytest tests/test_backdrop_file_sharing.py -v
"""

import io

import pytest
from PIL import Image as PilImage
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from api import routes_backdrops, storage
from database.base import Base
from database.models import Backdrop, Dealership, User

DEALERSHIP_ID = 1


@compiles(BigInteger, "sqlite")
def _bigint_is_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_ROOT", (tmp_path / "storage").resolve())

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Dealership(id=DEALERSHIP_ID, name="Ours", status="active"))
        session.add(
            User(
                id=1,
                dealership_id=DEALERSHIP_ID,
                email="dealer@ours.example",
                password_hash="x",
                first_name="A",
                last_name="Dealer",
                role="dealership_admin",
            )
        )
        session.flush()
        yield session


def _png(colour) -> bytes:
    buffer = io.BytesIO()
    PilImage.new("RGB", (24, 18), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _backdrop(session, name, content):
    stored = storage.save_image(DEALERSHIP_ID, "backdrop", content)
    row = Backdrop(
        dealership_id=DEALERSHIP_ID,
        name=name,
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        suits_angles=[],
    )
    session.add(row)
    session.flush()
    return row


def test_shared_file_survives_deleting_one_of_the_pair(session):
    content = _png((30, 60, 90))
    first = _backdrop(session, "Showroom A", content)
    second = _backdrop(session, "Showroom B", content)
    session.commit()

    # Content addressing means both rows point at exactly one file.
    assert first.storage_path == second.storage_path
    path = first.storage_path
    assert storage.resolve(path).is_file()

    routes_backdrops.delete_backdrop(first.id, session.get(User, 1), session)

    # The other row still references the file, so it must still be there.
    assert session.scalar(
        select(Backdrop).where(Backdrop.id == second.id)
    ) is not None
    assert storage.resolve(path).is_file(), (
        "deleting one backdrop removed the file the other one still uses"
    )


def test_file_is_removed_once_the_last_reference_goes(session):
    content = _png((30, 60, 90))
    first = _backdrop(session, "Showroom A", content)
    second = _backdrop(session, "Showroom B", content)
    session.commit()
    path = first.storage_path

    routes_backdrops.delete_backdrop(first.id, session.get(User, 1), session)
    routes_backdrops.delete_backdrop(second.id, session.get(User, 1), session)

    with pytest.raises(storage.StorageError):
        storage.resolve(path)


def test_unshared_file_is_removed_on_delete(session):
    only = _backdrop(session, "Solo", _png((200, 40, 10)))
    session.commit()
    path = only.storage_path
    assert storage.resolve(path).is_file()

    routes_backdrops.delete_backdrop(only.id, session.get(User, 1), session)

    with pytest.raises(storage.StorageError):
        storage.resolve(path)
