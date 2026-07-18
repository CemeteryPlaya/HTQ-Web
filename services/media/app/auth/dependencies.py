"""Authentication dependencies — validates cross-service JWTs.

Two kinds of JWT are accepted:

1. **User JWT**, signed with ``settings.jwt_secret`` (issued by user-service
   on login). Carries ``user_id`` and ``is_admin``.

2. **Service JWT**, signed with ``settings.service_jwt_secret``. Carries
   ``service=True`` and is issued by another HTQWeb service (e.g.,
   user-service forwarding an avatar upload). When present, the caller may
   pass ``X-User-Id`` so this service can still attribute ownership.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.settings import settings


security = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    """Normalised payload usable by both user and service JWTs."""

    sub: str | None = None
    user_id: int | None = None
    is_admin: bool = False
    is_service: bool = False
    exp: int | None = None


def _decode_user_jwt(token: str) -> TokenPayload | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
    except jwt.PyJWTError:
        return None
    return TokenPayload(
        sub=str(payload.get("sub")) if payload.get("sub") is not None else None,
        user_id=payload.get("user_id"),
        is_admin=bool(payload.get("is_admin", False)),
        is_service=False,
        exp=payload.get("exp"),
    )


def _decode_service_jwt(token: str, request: Request | None = None) -> TokenPayload | None:
    try:
        payload = jwt.decode(
            token,
            settings.service_jwt_secret,
            algorithms=[settings.service_jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
    except jwt.PyJWTError:
        return None
    if not payload.get("service"):
        return None

    # Service JWTs don't carry user_id directly — caller passes it via header
    # so this service can still credit owner_id on uploads.
    forwarded_user_id: int | None = None
    if request is not None:
        raw = request.headers.get("x-user-id")
        if raw:
            try:
                forwarded_user_id = int(raw)
            except ValueError:
                forwarded_user_id = None

    return TokenPayload(
        sub=payload.get("sub"),
        user_id=forwarded_user_id,
        is_admin=True,  # trusted internal caller
        is_service=True,
        exp=payload.get("exp"),
    )


def get_optional_user(
    request: Request,
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenPayload | None:
    """Return a TokenPayload if the request carries a valid user or service JWT."""
    if not auth:
        return None
    token = auth.credentials
    # Service JWTs are rarer — try user JWT first, then service.
    return _decode_user_jwt(token) or _decode_service_jwt(token, request)


def get_current_user(
    user: Annotated[TokenPayload | None, Depends(get_optional_user)],
) -> TokenPayload:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> TokenPayload:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return user
