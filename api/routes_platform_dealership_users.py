"""Platform-administrator management of any one dealership's own staff.

`/api/dealership/users` (routes_dealership_users.py) is scoped to the
caller's own `dealership_id` — a `dealership_admin` managing their own team.
A platform administrator belongs to no dealership at all, so that router is
simply unreachable for them; this is the same four operations (list, add,
reset a password, deactivate), scoped instead by an explicit dealership id in
the path and gated to `platform_admin`.

Deliberately a separate router rather than teaching the existing one to
accept two different actors with two different scoping rules — each stays a
single role, a single scope, easy to audit on its own.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.deps import DbSession, require_roles
from api.schemas import (
    DealershipUserCreate,
    DealershipUserOut,
    DealershipUserProvisionedOut,
    DealershipUserResetOut,
)
from api.security import hash_password
from database.models import AuditLog, Dealership, User

router = APIRouter(
    prefix="/api/platform/dealerships/{dealership_id}/users",
    tags=["Platform administration"],
)
PlatformAdministrator = Annotated[User, Depends(require_roles("platform_admin"))]


def _out(user: User) -> DealershipUserOut:
    return DealershipUserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
    )


def _dealership(session: DbSession, dealership_id: int) -> Dealership:
    dealership = session.get(Dealership, dealership_id)
    if dealership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dealership not found.")
    return dealership


def _target(session: DbSession, dealership_id: int, user_id: int) -> User:
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    # A wrong dealership_id reads as "not found", identically to a wrong
    # user_id — the same reasoning as _owned_listing elsewhere in this
    # codebase: a user belonging to a different dealership is indistinguishable
    # from one that does not exist.
    if user is None or user.dealership_id != dealership_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _audit(
    session: DbSession,
    actor: User,
    request: Request,
    dealership_id: int,
    action: str,
    outcome: str,
    target_id: int | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor.id,
            dealership_id=dealership_id,
            action=action,
            outcome=outcome,
            request_path=request.url.path,
            details=f"target_user_id={target_id}" if target_id is not None else None,
        )
    )
    session.commit()


@router.get("", response_model=list[DealershipUserOut])
def list_dealership_users(
    dealership_id: int,
    administrator: PlatformAdministrator,
    session: DbSession,
) -> list[DealershipUserOut]:
    _dealership(session, dealership_id)
    users = session.scalars(
        select(User)
        .where(User.dealership_id == dealership_id)
        .order_by(User.last_name, User.first_name, User.id)
    ).all()
    return [_out(user) for user in users]


@router.post(
    "", response_model=DealershipUserProvisionedOut, status_code=status.HTTP_201_CREATED
)
def add_dealership_user(
    dealership_id: int,
    payload: DealershipUserCreate,
    request: Request,
    administrator: PlatformAdministrator,
    session: DbSession,
) -> DealershipUserProvisionedOut:
    _dealership(session, dealership_id)
    email = str(payload.email).strip().lower()
    first_name, last_name = payload.first_name.strip(), payload.last_name.strip()
    if not first_name or not last_name:
        raise HTTPException(status_code=422, detail="First and last name are required.")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="That email address is already in use.")

    initial_password = secrets.token_urlsafe(24)
    user = User(
        dealership_id=dealership_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=payload.role,
        password_hash=hash_password(initial_password),
        is_active=True,
        must_change_password=True,
    )
    try:
        session.add(user)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=administrator.id,
                dealership_id=dealership_id,
                action="dealership_user_create",
                outcome="success",
                request_path=request.url.path,
                details=f"target_user_id={user.id}",
            )
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="That email address is already in use.")
    session.refresh(user)
    return DealershipUserProvisionedOut(user=_out(user), initial_password=initial_password)


@router.post("/{user_id}/reset-password", response_model=DealershipUserResetOut)
def reset_dealership_user_password(
    dealership_id: int,
    user_id: int,
    request: Request,
    administrator: PlatformAdministrator,
    session: DbSession,
) -> DealershipUserResetOut:
    _dealership(session, dealership_id)
    user = _target(session, dealership_id, user_id)
    if not user.is_active:
        raise HTTPException(
            status_code=409, detail="Activate this account before resetting its password."
        )
    initial_password = secrets.token_urlsafe(24)
    user.password_hash = hash_password(initial_password)
    user.must_change_password = True
    user.token_version += 1
    _audit(
        session, administrator, request, dealership_id,
        "dealership_user_reset", "success", user.id,
    )
    return DealershipUserResetOut(initial_password=initial_password)


@router.post("/{user_id}/deactivate", response_model=DealershipUserOut)
def deactivate_dealership_user(
    dealership_id: int,
    user_id: int,
    request: Request,
    administrator: PlatformAdministrator,
    session: DbSession,
) -> DealershipUserOut:
    _dealership(session, dealership_id)
    user = _target(session, dealership_id, user_id)
    user.is_active = False
    user.token_version += 1
    _audit(
        session, administrator, request, dealership_id,
        "dealership_user_deactivate", "success", user.id,
    )
    session.refresh(user)
    return _out(user)
