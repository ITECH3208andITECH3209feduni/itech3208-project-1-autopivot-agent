"""Authentication routes.

There is deliberately no registration endpoint. Per the product design, dealer
accounts are provisioned by AutoPivot rather than self-served, which is also why
users.must_change_password defaults to true.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

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

# The same answer api.deps gives any token it refuses.
_SESSION_REVOKED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _signed_in(session: Session, user: User, token_version: int) -> LoginResponse:
    """A session for user at token_version, as both login and a password
    change hand one back."""
    token, expires_in = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        dealership_id=user.dealership_id,
        token_version=token_version,
    )
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=serialise_user(session, user),
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

    logger.info("Login accepted — user_id=%s role=%s", user.id, user.role)

    return _signed_in(session, user, user.token_version)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, session: DbSession) -> UserOut:
    return serialise_user(session, user)


@router.post("/change-password", response_model=LoginResponse)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    session: DbSession,
) -> LoginResponse:
    """Change the caller's own password and sign out every session they had.

    Bumping token_version refuses every token issued before now, including the
    one this request was made with: a session left signed in on another
    device, or a stolen token, stops working immediately rather than when it
    expires. The caller carries on with the token in the response, which has
    the same shape as POST /auth/login's.
    """
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

    new_hash = hash_password(payload.new_password)

    # Compare-and-set against the version this request was authenticated at,
    # rather than writing the stale in-memory row back. An administrator's
    # reset or deactivation that commits while the hashing above runs has
    # already revoked this session; writing over it would undo the reset and
    # hand back a token that survives it.
    authenticated_at = user.token_version
    saved = session.execute(
        update(User)
        .where(
            User.id == user.id,
            User.token_version == authenticated_at,
            User.is_active.is_(True),
        )
        .values(
            password_hash=new_hash,
            must_change_password=False,
            token_version=authenticated_at + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if saved.rowcount != 1:
        session.rollback()
        logger.info("Password change refused — session revoked mid-request, user_id=%s", user.id)
        raise _SESSION_REVOKED
    session.commit()
    session.refresh(user)

    logger.info("Password changed, earlier sessions revoked — user_id=%s", user.id)
    # The version written above, not whatever the row holds by now: a later
    # revocation must not be folded into the token handed back.
    return _signed_in(session, user, authenticated_at + 1)
