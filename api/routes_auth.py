"""Authentication routes.

There is deliberately no registration endpoint. Per the product design, dealer
accounts are provisioned by AutoPivot rather than self-served, which is also why
users.must_change_password defaults to true.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.deps import CurrentUser, DbSession, serialise_user
from api.schemas import ChangePasswordRequest, LoginRequest, LoginResponse, UserOut
from api.security import (
    create_access_token,
    hash_password,
    verify_password,
    waste_password_time,
)
from database.models import User

logger = logging.getLogger("autopivot.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Unknown email, wrong password and deactivated account all return this. The
# distinction is recorded in the log, never in the response.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password.",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: DbSession) -> LoginResponse:
    email = payload.email.strip().lower()

    user = session.scalar(select(User).where(User.email == email))

    if user is None:
        # Verify against a decoy hash so a missing account takes the same time
        # as a real one, keeping this endpoint from confirming which emails exist.
        waste_password_time()
        logger.info("Login rejected — unknown email")
        raise _INVALID_CREDENTIALS

    if not verify_password(payload.password, user.password_hash):
        logger.info("Login rejected — bad password for user_id=%s", user.id)
        raise _INVALID_CREDENTIALS

    if not user.is_active:
        logger.info("Login rejected — inactive account user_id=%s", user.id)
        raise _INVALID_CREDENTIALS

    token, expires_in = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        dealership_id=user.dealership_id,
    )

    logger.info("Login accepted — user_id=%s role=%s", user.id, user.role)

    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=serialise_user(session, user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, session: DbSession) -> UserOut:
    return serialise_user(session, user)


@router.post("/change-password", response_model=UserOut)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    session: DbSession,
) -> UserOut:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must differ from the current one.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    session.commit()
    session.refresh(user)

    logger.info("Password changed — user_id=%s", user.id)
    return serialise_user(session, user)
