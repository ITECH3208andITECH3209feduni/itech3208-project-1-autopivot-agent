"""Session revocation around passwords.

Changing your own password has to sign out every session you had: a token
left signed in on another device, or stolen, otherwise stays good for its full
lifetime. And an administrator must not be able to reset their own password
from the team page, which revokes the very session they are using and hands
the only way back in to a one-time password shown once.

POST /auth/change-password therefore answers exactly as POST /auth/login does,
with a fresh token carrying the new token_version; the web and mobile clients
carry on with it.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes_auth
from api.app import create_app
from api.deps import get_db_session
from api.security import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET, hash_password
from database.base import Base
from database.models import Dealership, User

ADMIN = "admin@first.example.com"
STAFF = "staff@first.example.com"
ADMIN_PASSWORD = "AdminPassword123"
STAFF_PASSWORD = "StaffPassword123"
NEW_PASSWORD = "A-new-private-password-123"


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        dealership = Dealership(name="First Motors", location="Ballarat")
        session.add(dealership)
        session.flush()
        accounts = [
            User(dealership_id=dealership.id, email=ADMIN, first_name="First", last_name="Admin",
                 role="dealership_admin", password_hash=hash_password(ADMIN_PASSWORD),
                 is_active=True, must_change_password=False),
            User(dealership_id=dealership.id, email=STAFF, first_name="First", last_name="Staff",
                 role="dealership_staff", password_hash=hash_password(STAFF_PASSWORD),
                 is_active=True, must_change_password=False),
        ]
        session.add_all(accounts)
        session.commit()
        ids = {account.email: account.id for account in accounts}
    app = create_app()

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    return TestClient(app), sessions, ids


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password) -> dict:
    result = client.post("/auth/login", json={"email": email, "password": password})
    assert result.status_code == 200, result.text
    return result.json()


def token_version(sessions, user_id) -> int:
    with sessions() as session:
        return session.get(User, user_id).token_version


def change(client, token, current, new=NEW_PASSWORD):
    return client.post("/auth/change-password", headers=bearer(token),
                       json={"current_password": current, "new_password": new})


# --- BUG 1: changing your password signs out every other session -------------


def test_changing_password_refuses_every_token_issued_before_it(setup):
    client, _, _ = setup
    laptop = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    phone = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    assert client.get("/auth/me", headers=bearer(phone)).status_code == 200

    changed = change(client, laptop, STAFF_PASSWORD)

    assert changed.status_code == 200, changed.text
    # The session left signed in elsewhere, and the one that made the change.
    assert client.get("/auth/me", headers=bearer(phone)).status_code == 401
    assert client.get("/auth/me", headers=bearer(laptop)).status_code == 401
    # The caller carries on with the token it was handed.
    fresh = changed.json()["access_token"]
    me = client.get("/auth/me", headers=bearer(fresh))
    assert me.status_code == 200
    assert me.json()["email"] == STAFF


def test_change_password_answers_exactly_as_login_does(setup):
    client, sessions, ids = setup
    signed_in = login(client, STAFF, STAFF_PASSWORD)
    before = token_version(sessions, ids[STAFF])

    changed = change(client, signed_in["access_token"], STAFF_PASSWORD)

    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert set(body) == set(signed_in) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == signed_in["expires_in"] == ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert set(body["user"]) == set(signed_in["user"])
    assert body["user"]["id"] == ids[STAFF]
    assert body["user"]["email"] == STAFF
    assert body["user"]["must_change_password"] is False
    assert body["user"]["dealership"]["name"] == "First Motors"
    # The returned token carries the version the change moved the account to.
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert token_version(sessions, ids[STAFF]) == before + 1
    assert claims["token_version"] == before + 1
    assert claims["sub"] == str(ids[STAFF])


def test_new_password_signs_in_and_the_old_one_no_longer_does(setup):
    client, _, _ = setup
    token = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    assert change(client, token, STAFF_PASSWORD).status_code == 200

    assert client.post("/auth/login", json={"email": STAFF, "password": STAFF_PASSWORD}).status_code == 401
    again = login(client, STAFF, NEW_PASSWORD)
    assert client.get("/auth/me", headers=bearer(again["access_token"])).status_code == 200


def test_initial_password_change_hands_back_a_token_that_can_use_the_app(setup):
    client, sessions, ids = setup
    with sessions() as session:
        session.get(User, ids[STAFF]).must_change_password = True
        session.commit()
    token = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    assert client.get("/api/dashboard/counts", headers=bearer(token)).status_code == 403

    changed = change(client, token, STAFF_PASSWORD)

    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["must_change_password"] is False
    assert client.get("/api/dashboard/counts", headers=bearer(changed.json()["access_token"])).status_code == 200
    assert client.get("/api/dashboard/counts", headers=bearer(token)).status_code == 401


def test_a_refused_change_leaves_the_session_and_password_alone(setup):
    client, sessions, ids = setup
    token = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    before = token_version(sessions, ids[STAFF])

    wrong = change(client, token, "Not-the-current-password-1")
    same = change(client, token, STAFF_PASSWORD, new=STAFF_PASSWORD)
    short = change(client, token, STAFF_PASSWORD, new="short")
    anonymous = client.post("/auth/change-password",
                            json={"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD})

    assert (wrong.status_code, wrong.json()["detail"]) == (400, "Current password is incorrect.")
    assert (same.status_code, same.json()["detail"]) == (400, "The new password must differ from the current one.")
    assert short.status_code == 422
    assert anonymous.status_code == 401
    assert token_version(sessions, ids[STAFF]) == before
    assert client.get("/auth/me", headers=bearer(token)).status_code == 200
    login(client, STAFF, STAFF_PASSWORD)


def test_a_reset_landing_while_the_change_is_in_flight_is_not_written_over(setup, monkeypatch):
    """An administrator's reset commits between this request being authenticated
    and it saving the new password. The reset has already revoked the session
    the change was made with, so the change must fail rather than overwrite the
    reset and hand back a token that survives it."""
    client, sessions, ids = setup
    token = login(client, STAFF, STAFF_PASSWORD)["access_token"]
    one_time = "Administrator-issued-one-time-1"
    real_hash = routes_auth.hash_password

    def hash_while_an_administrator_resets(plain):
        with sessions() as other:
            target = other.get(User, ids[STAFF])
            target.password_hash = real_hash(one_time)
            target.must_change_password = True
            target.token_version += 1
            other.commit()
        return real_hash(plain)

    monkeypatch.setattr(routes_auth, "hash_password", hash_while_an_administrator_resets)
    changed = change(client, token, STAFF_PASSWORD)
    monkeypatch.undo()

    assert changed.status_code == 401, changed.text
    assert "access_token" not in changed.json()
    # The reset stands: its one-time password works and must still be changed.
    after_reset = login(client, STAFF, one_time)
    assert after_reset["user"]["must_change_password"] is True
    assert client.post("/auth/login", json={"email": STAFF, "password": NEW_PASSWORD}).status_code == 401
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


# --- BUG 2: an administrator cannot reset their own password -----------------


def test_administrator_cannot_reset_their_own_password(setup):
    client, sessions, ids = setup
    token = login(client, ADMIN, ADMIN_PASSWORD)["access_token"]
    before = token_version(sessions, ids[ADMIN])

    refused = client.post(f"/api/dealership/users/{ids[ADMIN]}/reset-password", headers=bearer(token))

    assert refused.status_code == 409, refused.text
    assert "Change password" in refused.json()["detail"]
    assert "initial_password" not in refused.json()
    # Still signed in, on the same password, with nothing left to change.
    me = client.get("/auth/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False
    assert token_version(sessions, ids[ADMIN]) == before
    login(client, ADMIN, ADMIN_PASSWORD)


def test_administrator_can_still_reset_a_colleague(setup):
    client, _, ids = setup
    admin = login(client, ADMIN, ADMIN_PASSWORD)["access_token"]
    staff = login(client, STAFF, STAFF_PASSWORD)["access_token"]

    reset = client.post(f"/api/dealership/users/{ids[STAFF]}/reset-password", headers=bearer(admin))

    assert reset.status_code == 200, reset.text
    assert client.get("/auth/me", headers=bearer(staff)).status_code == 401
    assert client.get("/auth/me", headers=bearer(admin)).status_code == 200
    assert login(client, STAFF, reset.json()["initial_password"])["user"]["must_change_password"] is True
