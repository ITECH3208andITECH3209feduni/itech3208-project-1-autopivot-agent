"""Shared FastAPI dependencies — database sessions and the authenticated user."""

from __future__ import annotations

from typing import Annotated, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.schemas import DealershipOut, UserOut
from api.security import decode_access_token
from database.connection import get_db_session
from database.models import User

# auto_error=False so a missing header produces our own 401 with a WWW-Authenticate
# challenge rather than Starlette's bare 403.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db_session)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    session: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        # Expired, wrong signature, malformed — all indistinguishable to the
        # caller on purpose.
        raise _UNAUTHENTICATED

    subject = payload.get("sub")
    if subject is None:
        raise _UNAUTHENTICATED

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise _UNAUTHENTICATED

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        # The account may have been deactivated after the token was issued, so
        # this is re-checked on every request rather than trusted from the token.
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[[User], User]:
    """Dependency factory restricting an endpoint to the given roles."""

    def _guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account does not have access to this resource.",
            )
        return user

    return _guard


def serialise_user(session: Session, user: User) -> UserOut:
    """Build the client-facing user payload, including dealership context.

    The sidebar shows the dealership name and its active user count, so that
    count is resolved here rather than with a second round trip.
    """
    dealership = None
    if user.dealership is not None:
        user_count = session.scalar(
            select(func.count(User.id)).where(
                User.dealership_id == user.dealership.id,
                User.is_active.is_(True),
            )
        )
        dealership = DealershipOut(
            id=user.dealership.id,
            name=user.dealership.name,
            location=user.dealership.location,
            status=user.dealership.status,
            user_count=user_count or 0,
        )

    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        dealership=dealership,
    )
