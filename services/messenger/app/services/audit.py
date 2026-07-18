"""Audit log helper — call ``record_action`` from sensitive write paths."""

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.logging import get_logger
from app.models.audit_log import AuditLog


log = get_logger(__name__)


async def record_action(
    session: AsyncSession,
    *,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    changes: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> AuditLog:
    """Persist an audit entry and emit a structured log event.

    Call from:
      * admin CRUD (create/update/delete)
      * auth events (login, logout, token refresh, OAuth connect/disconnect)
      * DLP blocks, rate-limit rejections
    """
    ip = None
    user_agent = None
    correlation_id = None
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        correlation_id = getattr(request.state, "correlation_id", None)

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        changes=changes,
        ip_address=ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    session.add(entry)
    await session.flush()

    log.info(
        "audit_log_recorded",
        action=action,
        resource_type=resource_type,
        resource_id=entry.resource_id,
        user_id=user_id,
    )
    return entry
