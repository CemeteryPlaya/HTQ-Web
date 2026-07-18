"""FastAPI dependencies — JWT validation entry points.

Two flavours:

* ``get_current_user`` — strict, raises 401 when the bearer header is missing
  or invalid. Default for protected endpoints.
* ``get_optional_user`` — soft, returns ``None`` for anonymous requests. Used
  by endpoints that have a public read mode but enrich the response when the
  caller is logged in (e.g. CMS news, messenger room previews).

The underlying ``HTTPBearer`` is configured with ``auto_error=False`` so we
can render a uniform ``WWW-Authenticate`` header and a consistent error body
regardless of whether the header is missing vs. malformed.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import auth_settings
from .payload import TokenPayload


# ``auto_error=False`` so missing-header is reported by *our* code (uniform
# 401 body), not by FastAPI's default 403 from HTTPBearer.
security = HTTPBearer(auto_error=False)


def _decode(token: str) -> TokenPayload:
    """Decode a JWT and convert it to a ``TokenPayload``.

    Raises 401 on any decode/validation failure. The original ``jwt`` exception
    is *not* leaked to clients — only a short summary in ``detail``.
    """
    try:
        payload = jwt.decode(
            token,
            auth_settings.jwt_secret,
            algorithms=[auth_settings.jwt_algorithm],
            issuer=auth_settings.jwt_issuer or None,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenPayload(**payload)


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenPayload | None:
    """Return ``TokenPayload`` if the request carries a valid bearer token, else ``None``.

    Used by endpoints with a public read path. A *malformed* token still
    returns ``None`` here — endpoints that want to reject malformed tokens
    explicitly should depend on ``get_current_user`` instead.
    """
    if credentials is None:
        return None
    try:
        return _decode(credentials.credentials)
    except HTTPException:
        return None


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenPayload:
    """Require a valid bearer token. Raises 401 when missing/invalid/expired."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode(credentials.credentials)
