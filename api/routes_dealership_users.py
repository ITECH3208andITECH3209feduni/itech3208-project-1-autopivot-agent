"""Dealership-scoped staff provisioning, reset and deactivation."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.deps import DbSession, require_roles
from api.schemas import (
    DealershipUserCreate, DealershipUserOut, DealershipUserProvisionedOut,
    DealershipUserResetOut,
)
from api.security import hash_password
from database.models import AuditLog, User

router = APIRouter(prefix="/api/dealership/users", tags=["Dealership user management"])
DealershipAdministrator = Annotated[User, Depends(require_roles("dealership_admin"))]


def _out(user: User) -> DealershipUserOut:
    return DealershipUserOut(
        id=user.id, email=user.email, first_name=user.first_name,
        last_name=user.last_name, role=user.role, is_active=user.is_active,
        must_change_password=user.must_change_password,
    )


def _audit(session: DbSession, actor: User, request: Request, action: str,
           outcome: str, target_id: int | None = None) -> None:
    session.add(AuditLog(
        actor_user_id=actor.id, dealership_id=actor.dealership_id,
        action=action, outcome=outcome, request_path=request.url.path,
        details=f"target_user_id={target_id}" if target_id is not None else None,
    ))
    session.commit()


def _deny(session: DbSession, actor: User, request: Request,
          action: str, target_id: int | None = None) -> None:
    _audit(session, actor, request, action, "denied", target_id)
    raise HTTPException(status_code=403, detail="You cannot manage users outside your dealership.")


def _target(session: DbSession, actor: User, request: Request,
            user_id: int, action: str) -> User:
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.dealership_id != actor.dealership_id:
        _deny(session, actor, request, action, user_id)
    return user


@router.get("", response_model=list[DealershipUserOut])
def list_users(request: Request, administrator: DealershipAdministrator,
               session: DbSession, dealership_id: int | None = Query(default=None)):
    if dealership_id is not None and dealership_id != administrator.dealership_id:
        _deny(session, administrator, request, "dealership_user_list")
    users = session.scalars(select(User).where(
        User.dealership_id == administrator.dealership_id,
    ).order_by(User.last_name, User.first_name, User.id)).all()
    return [_out(user) for user in users]


@router.post("", response_model=DealershipUserProvisionedOut,
             status_code=status.HTTP_201_CREATED)
def add_user(payload: DealershipUserCreate, request: Request,
             administrator: DealershipAdministrator, session: DbSession):
    if payload.dealership_id is not None and payload.dealership_id != administrator.dealership_id:
        _deny(session, administrator, request, "dealership_user_create")
    email = str(payload.email).strip().lower()
    first_name, last_name = payload.first_name.strip(), payload.last_name.strip()
    if not first_name or not last_name:
        raise HTTPException(status_code=422, detail="First and last name are required.")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="That email address is already in use.")

    initial_password = secrets.token_urlsafe(24)
    user = User(
        dealership_id=administrator.dealership_id, email=email,
        first_name=first_name, last_name=last_name, role=payload.role,
        password_hash=hash_password(initial_password), is_active=True,
        must_change_password=True,
    )
    try:
        session.add(user)
        session.flush()
        session.add(AuditLog(
            actor_user_id=administrator.id, dealership_id=administrator.dealership_id,
            action="dealership_user_create", outcome="success", request_path=request.url.path,
            details=f"target_user_id={user.id}",
        ))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="That email address is already in use.")
    session.refresh(user)
    return DealershipUserProvisionedOut(user=_out(user), initial_password=initial_password)


@router.post("/{user_id}/reset-password", response_model=DealershipUserResetOut)
def reset_password(user_id: int, request: Request,
                   administrator: DealershipAdministrator, session: DbSession):
    user = _target(session, administrator, request, user_id, "dealership_user_reset")
    if not user.is_active:
        raise HTTPException(status_code=409, detail="Activate this account before resetting its password.")
    initial_password = secrets.token_urlsafe(24)
    user.password_hash = hash_password(initial_password)
    user.must_change_password = True
    user.token_version += 1
    _audit(session, administrator, request, "dealership_user_reset", "success", user.id)
    return DealershipUserResetOut(initial_password=initial_password)


@router.post("/{user_id}/deactivate", response_model=DealershipUserOut)
def deactivate_user(user_id: int, request: Request,
                    administrator: DealershipAdministrator, session: DbSession):
    user = _target(session, administrator, request, user_id, "dealership_user_deactivate")
    if user.id == administrator.id:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
    user.is_active = False
    user.token_version += 1
    _audit(session, administrator, request, "dealership_user_deactivate", "success", user.id)
    session.refresh(user)
    return _out(user)
