"""Platform-administrator dealership onboarding and listing routes."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api import storage
from api.deps import DbSession, require_roles, serialise_user
from api.schemas import (
    DealershipOnboardRequest,
    DealershipOut,
    DealershipProvisionedOut,
)
from api.security import hash_password
from database.models import AuditLog, Dealership, User

logger = logging.getLogger("autopivot.platform_admin")

router = APIRouter(prefix="/api/platform/dealerships", tags=["Platform administration"])
PlatformAdministrator = Annotated[User, Depends(require_roles("platform_admin"))]


def _clean(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} is required.",
        )
    return value


def _serialise_dealership(session: DbSession, dealership: Dealership) -> DealershipOut:
    user_count = session.scalar(
        select(func.count(User.id)).where(
            User.dealership_id == dealership.id,
            User.is_active.is_(True),
        )
    )
    return DealershipOut(
        id=dealership.id,
        name=dealership.name,
        location=dealership.location,
        contact_name=dealership.contact_name,
        contact_email=dealership.contact_email,
        contact_phone=dealership.contact_phone,
        status=dealership.status,
        user_count=user_count or 0,
    )


@router.get("", response_model=list[DealershipOut])
def list_dealerships(
    administrator: PlatformAdministrator,
    session: DbSession,
) -> list[DealershipOut]:
    rows = session.scalars(select(Dealership).order_by(Dealership.name)).all()
    return [_serialise_dealership(session, row) for row in rows]


@router.post(
    "",
    response_model=DealershipProvisionedOut,
    status_code=status.HTTP_201_CREATED,
)
def onboard_dealership(
    payload: DealershipOnboardRequest,
    administrator: PlatformAdministrator,
    session: DbSession,
) -> DealershipProvisionedOut:
    name = _clean(payload.name, "Dealership name")
    location = _clean(payload.location, "Location")
    contact_name = _clean(payload.contact_name, "Contact name")
    contact_phone = _clean(payload.contact_phone, "Contact phone")
    first_name = _clean(payload.admin_first_name, "Administrator first name")
    last_name = _clean(payload.admin_last_name, "Administrator last name")
    contact_email = str(payload.contact_email).strip().lower()
    admin_email = str(payload.admin_email).strip().lower()

    duplicate_name = session.scalar(
        select(Dealership.id).where(func.lower(Dealership.name) == name.lower())
    )
    if duplicate_name is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dealership with that name already exists.",
        )

    duplicate_email = session.scalar(select(User.id).where(User.email == admin_email))
    if duplicate_email is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email address is already in use.",
        )

    initial_password = secrets.token_urlsafe(12)
    dealership: Dealership | None = None
    storage_created = False

    try:
        dealership = Dealership(
            name=name,
            location=location,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            status="active",
        )
        session.add(dealership)
        session.flush()

        storage.provision_dealership(dealership.id)
        storage_created = True

        first_administrator = User(
            dealership_id=dealership.id,
            email=admin_email,
            password_hash=hash_password(initial_password),
            first_name=first_name,
            last_name=last_name,
            role="dealership_admin",
            is_active=True,
            must_change_password=True,
        )
        session.add(first_administrator)
        session.flush()

        session.add(
            AuditLog(
                actor_user_id=administrator.id,
                dealership_id=dealership.id,
                action="dealership_onboarded",
                outcome="success",
                request_path="/api/platform/dealerships",
                details=f"Created dealership and first administrator user_id={first_administrator.id}",
            )
        )
        session.commit()
    except FileExistsError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Storage for that dealership already exists.",
        )
    except IntegrityError:
        session.rollback()
        if dealership is not None and storage_created:
            storage.remove_provisioned_dealership(dealership.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The dealership name or administrator email is already in use.",
        )
    except Exception:
        session.rollback()
        if dealership is not None and storage_created:
            storage.remove_provisioned_dealership(dealership.id)
        logger.exception("Dealership onboarding failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dealership onboarding failed. No account was created.",
        )

    session.refresh(dealership)
    session.refresh(first_administrator)
    logger.info("Dealership onboarded — id=%s", dealership.id)
    return DealershipProvisionedOut(
        dealership=_serialise_dealership(session, dealership),
        administrator=serialise_user(session, first_administrator),
        initial_password=initial_password,
    )
