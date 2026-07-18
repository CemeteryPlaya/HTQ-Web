"""Auth configuration for the shared `htqweb_auth` package.

Fail-Fast policy: ``JWT_SECRET`` MUST be present in the environment. There is
no default — importing this module without the variable raises
``pydantic.ValidationError`` immediately, which is intentional. A microservice
silently accepting tokens signed with a placeholder secret is far worse than
a startup crash that the operator cannot miss.

Tests bypass this by setting ``os.environ["JWT_SECRET"]`` at the top of
``conftest.py`` before any application import (see
``services/email/tests/conftest.py`` for the canonical pattern).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """JWT validation configuration shared by every microservice.

    Values are read exclusively from process environment variables — we do
    not load a ``.env`` file here. Services that rely on ``.env`` for local
    development should let their own ``app.core.settings`` (or docker-compose)
    populate the environment first; this package only reads what is already
    there.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # Fail-Fast: no default. ``...`` (Ellipsis) marks the field as required.
    jwt_secret: str = Field(..., min_length=1, description="HMAC secret used to verify JWTs from user-service.")

    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm; must match user-service.")
    jwt_issuer: str = Field(default="htqweb-auth", description="Expected `iss` claim. Set to empty string to disable issuer check.")


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return a cached ``AuthSettings`` instance.

    Wrapped in ``lru_cache`` so the (potentially failing) constructor only runs
    once per process. The first caller eats the ``ValidationError`` if
    ``JWT_SECRET`` is missing — every subsequent caller gets the cached object.
    """
    return AuthSettings()


# Module-level singleton — eager so misconfiguration surfaces at import time
# rather than on the first authenticated request.
auth_settings: AuthSettings = get_auth_settings()
