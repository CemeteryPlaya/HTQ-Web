"""
Authentication service — password hashing, JWT generation/validation.

This service is the JWT authority for the entire HTQWeb platform.
All other services validate tokens using the same secret.
"""

import base64
import datetime
import hashlib
import hmac
import re
from typing import Optional

import bcrypt
import jwt
from pydantic import BaseModel

from app.core.settings import settings


# ─── Password hashing ───────────────────────────────────────────────────────
# New passwords are hashed with bcrypt. Hashes migrated from the legacy
# Django backend use PBKDF2-SHA256 (`pbkdf2_sha256$iterations$salt$hash`);
# they are verified with pure hashlib (no Django dependency) and upgraded
# to bcrypt on the next successful login (see needs_rehash).

# Regex to detect legacy PBKDF2 hashes: pbkdf2_sha256$iterations$salt$hash
_DJANGO_PBKDF2_RE = re.compile(r'^pbkdf2_sha256\$\d+\$.+')


def _verify_django_pbkdf2(plain_password: str, hashed: str) -> bool:
    """
    Verify a legacy Django-format PBKDF2-SHA256 hash without Django:
    hash = base64(pbkdf2_hmac(sha256, password, salt, iterations)).
    """
    try:
        _algorithm, iterations, salt, b64_hash = hashed.split("$", 3)
        expected = base64.b64decode(b64_hash)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.
    Supports both Django PBKDF2 and bcrypt — transparent migration.
    """
    if _DJANGO_PBKDF2_RE.match(hashed_password):
        return _verify_django_pbkdf2(plain_password, hashed_password)
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except ValueError:
        # Not a bcrypt hash (e.g. the legacy "__placeholder_sync__" marker
        # or a corrupt value) — treat as wrong password, not a 500.
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Check if a password hash should be upgraded to bcrypt."""
    # Django PBKDF2 hashes need rehashing
    if _DJANGO_PBKDF2_RE.match(hashed_password):
        return True
    # Check bcrypt rounds (if needed in the future)
    return False


class TokenPair(BaseModel):
    """JWT access + refresh token pair."""
    access: str
    refresh: str
    token_type: str = "Bearer"


class TokenPayload(BaseModel):
    """Decoded JWT payload with custom claims.

    Refresh tokens deliberately carry only ``user_id`` + bookkeeping; the
    auth claims (username/email/is_staff/...) are re-derived from the DB
    on each refresh. The fields below are therefore Optional with safe
    defaults so the same model validates both shapes.
    """
    user_id: int
    username: Optional[str] = None
    email: Optional[str] = None
    is_staff: bool = False
    is_superuser: bool = False
    is_admin: bool = False
    token_type: str = "access"  # "access" or "refresh"
    exp: datetime.datetime
    iat: Optional[datetime.datetime] = None
    iss: Optional[str] = None


def create_token_pair(
    user_id: int,
    username: str,
    email: str,
    is_staff: bool = False,
    is_superuser: bool = False,
) -> TokenPair:
    """
    Create JWT access + refresh token pair.

    Tokens contain custom claims (username, email, is_staff, is_superuser, is_admin)
    so downstream services can authorize without calling this service.
    The `is_admin` claim is derived from `is_staff or is_superuser` and is the
    single source of truth for sqladmin access across all services.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    is_admin = bool(is_staff or is_superuser)

    access_payload = {
        # Standard "sub" claim (RFC 7519). Grafana's [auth.jwt] SSO refuses
        # tokens without it — silently, with a bare 401.
        "sub": str(user_id),
        "user_id": user_id,
        "username": username,
        "email": email,
        "is_staff": is_staff,
        "is_superuser": is_superuser,
        "is_admin": is_admin,
        "token_type": "access",
        "iat": now,
        "exp": now + datetime.timedelta(hours=2),
        "iss": settings.jwt_issuer,
    }

    refresh_payload = {
        "user_id": user_id,
        "token_type": "refresh",
        "iat": now,
        "exp": now + datetime.timedelta(days=7),
        "iss": settings.jwt_issuer,
    }

    access_token = jwt.encode(
        access_payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    refresh_token = jwt.encode(
        refresh_payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    return TokenPair(access=access_token, refresh=refresh_token)


def decode_token(token: str, require_type: Optional[str] = None) -> TokenPayload:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT string
        require_type: If set, verify token_type claim (e.g. "access" or "refresh")
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
    )

    if require_type and payload.get("token_type") != require_type:
        raise jwt.InvalidTokenError(
            f"Invalid token type: expected '{require_type}', got '{payload.get('token_type')}'"
        )

    return TokenPayload(**payload)
