"""Canonical decoded-JWT payload.

Superset of every field that any HTQWeb microservice currently reads from a
user-service-issued token. Services are free to ignore fields they don't need
— ``model_config = {"extra": "ignore"}`` keeps the model forward-compatible if
user-service starts emitting additional claims.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TokenPayload(BaseModel):
    """Decoded JWT payload, normalised across all services."""

    model_config = ConfigDict(extra="ignore")

    user_id: int
    exp: int
    token_type: str = "access"

    username: str | None = None
    email: str | None = None

    is_staff: bool = False
    is_superuser: bool = False
    is_admin: bool = False

    iat: int | None = None
    iss: str | None = None

    @property
    def is_elevated(self) -> bool:
        """Coarse 'has admin-ish privileges' check.

        Mirrors the historical behaviour of services/task/app/auth: any of
        the three flags being true is enough — user-service sets ``is_admin``
        as ``is_staff or is_superuser``, but we don't rely on that and check
        all three explicitly.
        """
        return bool(self.is_admin or self.is_staff or self.is_superuser)
