"""Password hashing and access-token issuing.

bcrypt is used directly rather than through passlib: passlib 1.7.4 is
unmaintained and trips a spurious version-detection error against bcrypt 4.x,
and the two functions we need are a three-line wrapper either way.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

logger = logging.getLogger("autopivot.security")

JWT_ALGORITHM = "HS256"

# bcrypt silently ignores anything past the 72th byte, so a longer password
# would be accepted at signup and then match on a truncated prefix at login.
# Callers reject over-long passwords rather than letting that happen quietly.
BCRYPT_MAX_PASSWORD_BYTES = 72


# RFC 7518 §3.2 requires an HMAC key at least as long as the hash output, which
# is 32 bytes for SHA-256. PyJWT warns below this; we fail loudly instead.
MIN_JWT_SECRET_BYTES = 32


def _load_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if secret and secret != "change_me":
        if len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise RuntimeError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes "
                "(RFC 7518 §3.2 for HS256). Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return secret
    generated = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET is not set (or is still the placeholder). A random key was "
        "generated for this process — every restart will invalidate all issued "
        "tokens, and multiple workers will not accept each other's tokens. Set "
        "JWT_SECRET before deploying."
    )
    return generated


JWT_SECRET: str = _load_jwt_secret()
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))


def password_too_long(plain: str) -> bool:
    """True if bcrypt would truncate this password."""
    return len(plain.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES


def hash_password(plain: str) -> str:
    if password_too_long(plain):
        raise ValueError(
            f"Password exceeds bcrypt's {BCRYPT_MAX_PASSWORD_BYTES}-byte limit."
        )
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison. Malformed stored hashes verify as False."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# A real hash of a throwaway value. Login verifies against this when the email
# is unknown, so a missing account costs the same time as a wrong password and
# the endpoint does not become an account-enumeration oracle.
_DUMMY_HASH: str = hash_password(secrets.token_urlsafe(16))


def waste_password_time() -> None:
    verify_password("autopivot-nonexistent-account", _DUMMY_HASH)


def create_access_token(
    user_id: int,
    email: str,
    role: str,
    dealership_id: Optional[int],
    expires_minutes: Optional[int] = None,
) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    minutes = expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "dealership_id": dealership_id,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError on any problem."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
