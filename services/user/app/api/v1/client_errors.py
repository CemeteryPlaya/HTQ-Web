"""Collect errors and audit events emitted from the browser.

Two endpoints:

* ``POST /api/users/v1/client-errors`` — fatal/unhandled errors caught by
  the React ``AppErrorBoundary`` or ``window.onerror``/``unhandledrejection``
  listeners. Logged at level ``error``.

* ``POST /api/users/v1/client-events`` — user-action audit events (login,
  logout, CRUD). Logged at level ``info``.

Both endpoints accept anonymous calls (optional JWT) so logouts and
pre-login crashes are captured. Nothing is persisted to SQL — the structlog
event stream feeds Loki, which is the source of truth for browser telemetry.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import jwt
from app.core.settings import settings


log = structlog.get_logger(__name__)


router = APIRouter(prefix="/api/users/v1", tags=["client-telemetry"])
# auto_error=False so anonymous pre-login errors are still accepted
_optional_security = HTTPBearer(auto_error=False)


def _maybe_decode(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_security)],
) -> dict[str, Any] | None:
    """Decode a user JWT if one is present, otherwise return None.

    The browser may be unauthenticated (pre-login crash) — in that case the
    caller is anonymous and we still want to log the error.
    """
    if not creds:
        return None
    try:
        return jwt.decode(
            creds.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
    except jwt.PyJWTError:
        return None


class ClientErrorReport(BaseModel):
    message: str
    stack: str | None = None
    componentStack: str | None = None
    url: str
    userAgent: str | None = None
    userId: int | None = None
    timestamp: str | None = None


class UserActionEvent(BaseModel):
    action: str
    resource: str | None = None
    resourceId: str | int | None = None
    meta: dict[str, Any] | None = None
    url: str
    userAgent: str | None = None
    timestamp: str | None = None


@router.post("/client-errors", status_code=202)
@router.post("/client-errors/", status_code=202)
async def ingest_client_error(
    body: ClientErrorReport,
    request: Request,
    payload: Annotated[dict[str, Any] | None, Depends(_maybe_decode)] = None,
) -> dict[str, bool]:
    """Log a frontend fatal error at ERROR level so Loki alerts can fire."""
    log.error(
        "frontend_client_error",
        message=body.message,
        stack=body.stack,
        component_stack=body.componentStack,
        client_url=body.url,
        user_agent=body.userAgent,
        client_timestamp=body.timestamp,
        user_id=(payload or {}).get("user_id") or body.userId,
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}


@router.post("/client-events", status_code=202)
@router.post("/client-events/", status_code=202)
async def ingest_user_action(
    body: UserActionEvent,
    request: Request,
    payload: Annotated[dict[str, Any] | None, Depends(_maybe_decode)] = None,
) -> dict[str, bool]:
    """Log a user-action audit event at INFO level."""
    log.info(
        "frontend_user_action",
        action=body.action,
        resource=body.resource,
        resource_id=str(body.resourceId) if body.resourceId is not None else None,
        meta=body.meta,
        client_url=body.url,
        user_agent=body.userAgent,
        client_timestamp=body.timestamp,
        user_id=(payload or {}).get("user_id"),
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}
