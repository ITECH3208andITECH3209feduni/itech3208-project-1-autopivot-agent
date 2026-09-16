"""APA-237–241 platform-administration integration tests."""

import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import storage
from api.app import create_app
from api.deps import get_db_session
from api.security import create_access_token, hash_password
from database.base import Base
from database.models import AuditLog, Dealership, User


@pytest.fixture()
def environment(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    with sessions() as session:
        first = Dealership(name="First Motors", location="Melbourne", status="active")
        second = Dealership(name="Second Motors", location="Geelong", status="active")
        session.add_all([first, second])
        session.flush()
        users = [
            User(email="platform@autopivot.com.au", password_hash=hash_password("PlatformPass123"), first_name="Pat", last_name="Admin", role="platform_admin", is_active=True, must_change_password=False),
            User(dealership_id=first.id, email="admin@firstmotors.com.au", password_hash=hash_password("DealershipPass123"), first_name="First", last_name="Admin", role="dealership_admin", is_active=True, must_change_password=False),
            User(dealership_id=second.id, email="admin@secondmotors.com.au", password_hash=hash_password("DealershipPass123"), first_name="Second", last_name="Admin", role="dealership_admin", is_active=True, must_change_password=False),
            User(dealership_id=first.id, email="staff@firstmotors.com.au", password_hash=hash_password("DealershipPass123"), first_name="First", last_name="Staff", role="dealership_staff", is_active=True, must_change_password=False),
        ]
        session.add_all(users)
        session.commit()
        user_ids = {user.email: user.id for user in users}

    app = create_app()

    def database_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = database_override
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")
    return TestClient(app), sessions, user_ids, tmp_path / "storage"


def auth(user_id: int, email: str, role: str, dealership_id: int | None = None):
    token, _ = create_access_token(user_id, email, role, dealership_id)
    return {"Authorization": f"Bearer {token}"}


def payload(name="Third Motors", email="admin@thirdmotors.com.au"):
    return {
        "name": name,
        "location": "Ballarat",
        "contact_name": "Taylor Contact",
        "contact_email": "contact@thirdmotors.com.au",
        "contact_phone": "0400 000 000",
        "admin_email": email,
        "admin_first_name": "Taylor",
        "admin_last_name": "Admin",
    }


def test_platform_admin_can_onboard_and_list_dealerships(environment):
    client, sessions, users, storage_root = environment
    headers = auth(users["platform@autopivot.com.au"], "platform@autopivot.com.au", "platform_admin")

    response = client.post("/api/platform/dealerships", json=payload(), headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["dealership"]["name"] == "Third Motors"
    assert body["dealership"]["status"] == "active"
    assert body["administrator"]["role"] == "dealership_admin"
    assert body["administrator"]["must_change_password"] is True
    assert body["initial_password"]
    assert (storage_root / str(body["dealership"]["id"])).is_dir()

    listed = client.get("/api/platform/dealerships", headers=headers)
    assert listed.status_code == 200
    assert {row["name"] for row in listed.json()} == {
        "First Motors", "Second Motors", "Third Motors"
    }

    with sessions() as session:
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "dealership_onboarded",
                AuditLog.outcome == "success",
            )
        ) == 1


@pytest.mark.parametrize(
    ("email", "role"),
    [
        ("admin@firstmotors.com.au", "dealership_admin"),
        ("admin@secondmotors.com.au", "dealership_admin"),
        ("staff@firstmotors.com.au", "dealership_staff"),
    ],
)
def test_non_platform_roles_are_denied_and_logged(environment, email, role):
    client, sessions, users, _ = environment
    response = client.get(
        "/api/platform/dealerships",
        headers=auth(users[email], email, role, 1),
    )
    assert response.status_code == 403

    with sessions() as session:
        record = session.scalar(
            select(AuditLog).where(
                AuditLog.actor_user_id == users[email],
                AuditLog.outcome == "denied",
            )
        )
        assert record is not None
        assert record.request_path == "/api/platform/dealerships"


def test_duplicate_name_and_email_are_rejected(environment):
    client, sessions, users, _ = environment
    headers = auth(users["platform@autopivot.com.au"], "platform@autopivot.com.au", "platform_admin")

    assert client.post("/api/platform/dealerships", json=payload("first motors"), headers=headers).status_code == 409
    assert client.post("/api/platform/dealerships", json=payload("New Name", "admin@firstmotors.com.au"), headers=headers).status_code == 409

    with sessions() as session:
        assert session.scalar(select(func.count(Dealership.id))) == 2


def test_failure_after_storage_creation_rolls_everything_back(environment, monkeypatch):
    client, sessions, users, storage_root = environment
    headers = auth(users["platform@autopivot.com.au"], "platform@autopivot.com.au", "platform_admin")

    def fail_hash(_password):
        raise RuntimeError("simulated password failure")

    monkeypatch.setattr("api.routes_platform_admin.hash_password", fail_hash)
    response = client.post("/api/platform/dealerships", json=payload(), headers=headers)
    assert response.status_code == 500

    with sessions() as session:
        assert session.scalar(select(func.count(Dealership.id))) == 2
        assert session.scalar(select(func.count(User.id))) == 4
    assert not storage_root.exists() or not any(storage_root.iterdir())


def test_initial_password_change_is_enforced(environment):
    client, _, users, _ = environment
    platform_headers = auth(users["platform@autopivot.com.au"], "platform@autopivot.com.au", "platform_admin")
    created = client.post("/api/platform/dealerships", json=payload(), headers=platform_headers).json()

    login = client.post("/auth/login", json={
        "email": created["administrator"]["email"],
        "password": created["initial_password"],
    })
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/dashboard/counts", headers=user_headers).status_code == 403
    assert client.post("/auth/change-password", headers=user_headers, json={
        "current_password": created["initial_password"],
        "new_password": "A-new-private-password-123",
    }).status_code == 200
    assert client.get("/api/dashboard/counts", headers=user_headers).status_code == 200


def test_no_public_registration_route_exists(environment):
    client, _, _, _ = environment
    assert client.post("/auth/register", json={}).status_code == 404
    assert client.post("/auth/signup", json={}).status_code == 404
