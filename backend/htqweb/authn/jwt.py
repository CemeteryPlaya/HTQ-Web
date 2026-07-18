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


def _encode(claims: dict, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**claims, "token_type": token_type,
         "iat": int(now.timestamp()),
         "exp": int((now + ttl).timestamp())},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_token_pair(user) -> dict:
    claims = _base_claims(user)
    return {
        "access": _encode(claims, timedelta(minutes=settings.JWT_ACCESS_TTL_MIN), "access"),
        "refresh": _encode(claims, timedelta(days=settings.JWT_REFRESH_TTL_DAYS), "refresh"),
        "token_type": "Bearer",
    }


def decode_token(token: str) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.JWT_SECRET,
                         algorithms=[settings.JWT_ALGORITHM],
                         issuer=settings.JWT_ISSUER,
                         # PyJWT >=2.10 defaults verify_iat=True and rejects
                         # a future `iat`. `iat` is informational here, not a
                         # security boundary (exp/iss already enforce that),
                         # and cross-service clock skew is a known operational
                         # reality in this platform (see CLAUDE.md) — so we
                         # don't want a skewed clock silently invalidating
                         # otherwise-legitimate tokens. The original FastAPI
                         # `_decode` (libs/htqweb_auth/dependencies.py) only
                         # ever set `verify_exp` explicitly and inherits the
                         # same PyJWT default for `verify_iat`; it is not part
                         # of the documented platform JWT contract.
                         options={"verify_iat": False})
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    return TokenPayload(**raw)
