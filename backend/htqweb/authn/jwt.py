from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings

from .payload import TokenPayload


class AuthError(Exception):
    pass


def _base_claims(user) -> dict:
    return {
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_admin": user.is_staff or user.is_superuser,
        "iss": settings.JWT_ISSUER,
    }


def _refresh_claims(user) -> dict:
    """Minimal claim set for refresh tokens.

    Mirrors ``services/user/app/services/auth_service.py``'s
    ``create_token_pair``: a refresh token is long-lived (7 days), so it
    deliberately does NOT carry privilege flags or PII (username/email/
    is_staff/is_superuser/is_admin) — only enough to look the user back up.
    Auth claims are re-derived from the DB on every ``token/refresh/`` call
    (see ``apps.users.views.refresh_token``), so a refresh token can't hand
    out stale privileges even if it outlives a role change.
    """
    return {
        "sub": str(user.id),
        "user_id": user.id,
        "iss": settings.JWT_ISSUER,
    }


def _encode(claims: dict, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**claims, "token_type": token_type,
         "iat": int(now.timestamp()),
         "exp": int((now + ttl).timestamp())},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_token_pair(user) -> dict:
    return {
        "access": _encode(_base_claims(user), timedelta(minutes=settings.JWT_ACCESS_TTL_MIN), "access"),
        "refresh": _encode(_refresh_claims(user), timedelta(days=settings.JWT_REFRESH_TTL_DAYS), "refresh"),
        "token_type": "Bearer",
    }


def decode_token(token: str) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.JWT_SECRET,
                         algorithms=[settings.JWT_ALGORITHM],
                         issuer=settings.JWT_ISSUER)
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    return TokenPayload(**raw)
