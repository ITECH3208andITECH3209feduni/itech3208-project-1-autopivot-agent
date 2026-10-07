"""BUG 1 — cross-tenant file read through a `..` path segment.

`GET /api/files/{storage_path:path}` authorises by the first path segment of
the *raw* string (storage.dealership_of) and then serves storage.resolve(),
which only checks the *resolved* file is inside the storage root. So a path
like ``1/../2/original/<sha>.jpg`` passes dealership 1's ownership check yet
resolves to — and serves — dealership 2's file. Starlette percent-decodes
``%2e%2e`` before the route sees it, so an encoded request reaches the handler
with the traversal intact.

The schema is built on in-memory SQLite the same way tests/test_image_lineage.py
and tests/test_platform_administration.py do it, so none of this needs
PostgreSQL:

    pytest tests/test_file_access_scoping.py -v
"""

import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image as PilImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import storage
from api.app import create_app
from api.deps import get_db_session
from api.security import create_access_token, hash_password
from database.base import Base
from database.models import Dealership, User

DEALERSHIP_ID = 1
OTHER_DEALERSHIP_ID = 2


def _jpeg(colour) -> bytes:
    import io

    buffer = io.BytesIO()
    PilImage.new("RGB", (16, 12), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    # Never write into the repo's real storage/ — point the root at a temp dir.
    monkeypatch.setattr(storage, "STORAGE_ROOT", (tmp_path / "storage").resolve())

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add_all(
            [
                Dealership(id=DEALERSHIP_ID, name="Ours", status="active"),
                Dealership(id=OTHER_DEALERSHIP_ID, name="Theirs", status="active"),
            ]
        )
        session.add(
            User(
                id=1,
                dealership_id=DEALERSHIP_ID,
                email="dealer@ours.example",
                password_hash=hash_password("Password123"),
                first_name="A",
                last_name="Dealer",
                role="dealership_admin",
                is_active=True,
                must_change_password=False,
            )
        )
        session.commit()

    # One file per dealership, written through the real storage code path.
    ours = storage.save_image(DEALERSHIP_ID, "original", _jpeg((10, 20, 30)))
    theirs = storage.save_image(OTHER_DEALERSHIP_ID, "original", _jpeg((200, 100, 50)))

    app = create_app()

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    client = TestClient(app)
    return client, ours, theirs


def _headers():
    token, _ = create_access_token(1, "dealer@ours.example", "dealership_admin", DEALERSHIP_ID)
    return {"Authorization": f"Bearer {token}"}


def test_own_file_is_served(environment):
    client, ours, _theirs = environment
    response = client.get(f"/api/files/{ours.storage_path}", headers=_headers())
    assert response.status_code == 200
    assert response.content == storage.resolve(ours.storage_path).read_bytes()


def test_percent_encoded_traversal_to_another_tenant_is_refused(environment):
    """The exploit as a client can actually deliver it: %2e%2e reaches the route
    as ``1/../2/original/<sha>.jpg`` (an httpx client collapses a *raw* ``..``
    before sending, so the encoded form is what an attacker uses)."""
    client, _ours, theirs = environment
    # theirs.storage_path == "2/original/<sha>.jpg"
    encoded = f"/api/files/1/%2e%2e/{theirs.storage_path}"
    response = client.get(encoded, headers=_headers())
    assert response.status_code == 404, (
        "dealership 1 must not reach dealership 2's file via a .. segment"
    )


def test_raw_traversal_string_is_refused_at_the_handler(environment):
    """Called with the exact bytes a decoded ``..`` produces, bypassing any
    client-side normalisation, the handler must still refuse."""
    client, _ours, theirs = environment
    from api import routes_backdrops

    user = type("U", (), {"dealership_id": DEALERSHIP_ID, "role": "dealership_admin"})()
    with pytest.raises(HTTPException) as raised:
        # The session is only used to audit platform-admin requests.
        routes_backdrops.serve_file(f"1/../{theirs.storage_path}", user, session=None)
    assert raised.value.status_code == 404


def test_dealership_of_rejects_unsafe_paths():
    assert storage.dealership_of("1/original/x.jpg") == 1
    for bad in (
        "1/../2/original/x.jpg",   # parent traversal
        "1/./original/x.jpg",      # current-dir segment
        "/2/original/x.jpg",       # absolute
        "1//original/x.jpg",       # empty segment
        "../2/x.jpg",              # leading traversal
        "",                        # empty
        "1/..",                    # trailing traversal
    ):
        assert storage.dealership_of(bad) is None, bad


def test_resolve_rejects_unsafe_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_ROOT", (tmp_path / "storage").resolve())
    for bad in ("1/../2/x.jpg", "1/./x.jpg", "/etc/passwd", "1//x.jpg", "../x"):
        with pytest.raises(storage.StorageError):
            storage.resolve(bad)
