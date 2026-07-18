"""Service-to-service (S2S) JWT issuance.

When user-service needs to call media-service on behalf of a user
(e.g., uploading an avatar during profile PATCH), it issues a short-lived
"service" JWT signed with ``SERVICE_JWT_SECRET``. The downstream service
recognises the ``service=True`` claim and trusts the call as internal.

The end user's identity is passed out-of-band via the ``X-User-Id`` header
so the downstream service can attribute ownership correctly.
"""

from __future__ import annotations

import time

import jwt

from app.core.settings import settings


DEFAULT_TTL_SEC = 60


def issue_service_token(
    *,
    sub: str = "user-service",
    ttl_sec: int = DEFAULT_TTL_SEC,
    extra_claims: dict | None = None,
) -> str:
    """Return a JWT for internal service calls.

    Claims:
        sub         : originating service identifier
        iss         : same issuer as user JWTs (for consistency)
        service     : ``True`` — marker that this is an S2S token
        exp         : ``now + ttl_sec``
        (extras)    : merged from ``extra_claims``
    """
    now = int(time.time())
    claims: dict = {
        "sub": sub,
        "iss": settings.jwt_issuer,
        "service": True,
        "iat": now,
        "exp": now + ttl_sec,
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(
        claims,
        settings.service_jwt_secret,
        algorithm=settings.service_jwt_algorithm,
    )
