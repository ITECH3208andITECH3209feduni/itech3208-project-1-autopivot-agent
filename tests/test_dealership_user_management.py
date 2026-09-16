"""APA-231: two-dealership isolation and immediate JWT revocation."""

import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import create_app
from api.deps import get_db_session
from api.security import hash_password
from database.base import Base
from database.models import AuditLog, Dealership, User


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        first, second = Dealership(name="First Motors"), Dealership(name="Second Motors")
        session.add_all([first, second])
        session.flush()
        accounts = [
            User(dealership_id=first.id, email="admin@first.example.com", first_name="First", last_name="Admin", role="dealership_admin", password_hash=hash_password("FirstPassword123"), is_active=True, must_change_password=False),
            User(dealership_id=second.id, email="admin@second.example.com", first_name="Second", last_name="Admin", role="dealership_admin", password_hash=hash_password("SecondPassword123"), is_active=True, must_change_password=False),
            User(dealership_id=second.id, email="staff@second.example.com", first_name="Second", last_name="Staff", role="dealership_staff", password_hash=hash_password("SecondPassword123"), is_active=True, must_change_password=False),
        ]
        session.add_all(accounts)
        session.commit()
        ids = {account.email: account.id for account in accounts}
        dealership_ids = (first.id, second.id)
    app = create_app()

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    return TestClient(app), sessions, ids, dealership_ids


def login(client, email, password):
    result = client.post("/auth/login", json={"email": email, "password": password})
    assert result.status_code == 200
    return {"Authorization": f"Bearer {result.json()['access_token']}"}


def test_create_is_scoped_and_forces_password_change(setup):
    client, sessions, ids, (first, second) = setup
    a = login(client, "admin@first.example.com", "FirstPassword123")
    b = login(client, "admin@second.example.com", "SecondPassword123")
    payload = {"email": "new@first.example.com", "first_name": "New", "last_name": "Starter", "role": "dealership_staff"}
    result = client.post("/api/dealership/users", headers=a, json=payload)
    assert result.status_code == 201
    created = result.json()
    assert created["user"]["must_change_password"] is True
    assert {u["email"] for u in client.get("/api/dealership/users", headers=a).json()} == {"admin@first.example.com", "new@first.example.com"}
    assert {u["email"] for u in client.get("/api/dealership/users", headers=b).json()} == {"admin@second.example.com", "staff@second.example.com"}
    with sessions() as session:
        assert session.get(User, created["user"]["id"]).dealership_id == first
    assert client.post("/api/dealership/users", headers=b, json=payload).status_code == 409
    assert client.post("/api/dealership/users", headers=a, json={**payload, "email": "another@first.example.com", "dealership_id": second}).status_code == 403
    fresh = login(client, "new@first.example.com", created["initial_password"])
    assert client.get("/api/dealership/users", headers=fresh).status_code == 403
    assert client.get("/api/dashboard/counts", headers=fresh).status_code == 403
    changed = client.post("/auth/change-password", headers=fresh, json={"current_password": created["initial_password"], "new_password": "NewPasswordThatIsPrivate123"})
    assert changed.status_code == 200
    assert client.get("/api/dashboard/counts", headers=fresh).status_code == 200


def test_reset_and_deactivation_revoke_sessions_and_keep_user(setup):
    client, sessions, ids, _ = setup
    admin = login(client, "admin@second.example.com", "SecondPassword123")
    staff = login(client, "staff@second.example.com", "SecondPassword123")
    assert client.get("/auth/me", headers=staff).status_code == 200
    reset = client.post(f"/api/dealership/users/{ids['staff@second.example.com']}/reset-password", headers=admin)
    assert reset.status_code == 200
    assert client.get("/auth/me", headers=staff).status_code == 401
    assert client.post("/auth/login", json={"email": "staff@second.example.com", "password": "SecondPassword123"}).status_code == 401
    temporary = login(client, "staff@second.example.com", reset.json()["initial_password"])
    assert client.get("/api/dashboard/counts", headers=temporary).status_code == 403
    assert client.post("/auth/change-password", headers=temporary, json={"current_password": reset.json()["initial_password"], "new_password": "NewPasswordThatIsPrivate123"}).status_code == 200
    assert client.get("/api/dashboard/counts", headers=temporary).status_code == 200
    deactivated = client.post(f"/api/dealership/users/{ids['staff@second.example.com']}/deactivate", headers=admin)
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.get("/auth/me", headers=temporary).status_code == 401
    assert client.post("/auth/login", json={"email": "staff@second.example.com", "password": "NewPasswordThatIsPrivate123"}).status_code == 401
    with sessions() as session:
        retained = session.get(User, ids["staff@second.example.com"])
        assert retained is not None and not retained.is_active


def test_cross_dealership_actions_refused_and_audited(setup):
    client, sessions, ids, (first, second) = setup
    a = login(client, "admin@first.example.com", "FirstPassword123")
    foreign = ids["staff@second.example.com"]
    assert client.get(f"/api/dealership/users?dealership_id={second}", headers=a).status_code == 403
    assert client.post(f"/api/dealership/users/{foreign}/reset-password", headers=a).status_code == 403
    assert client.post(f"/api/dealership/users/{foreign}/deactivate", headers=a).status_code == 403
    with sessions() as session:
        denied = session.scalars(select(AuditLog).where(AuditLog.actor_user_id == ids["admin@first.example.com"], AuditLog.outcome == "denied")).all()
        assert {entry.action for entry in denied} == {"dealership_user_list", "dealership_user_reset", "dealership_user_deactivate"}
        assert session.get(User, foreign).is_active


def test_only_dealership_admin_can_manage_and_no_public_registration(setup):
    client, sessions, ids, _ = setup
    staff = login(client, "staff@second.example.com", "SecondPassword123")
    assert client.get("/api/dealership/users", headers=staff).status_code == 403
    assert client.post("/api/dealership/users", json={}).status_code == 401
    assert client.post("/auth/register", json={}).status_code == 404
    assert client.post("/auth/signup", json={}).status_code == 404
