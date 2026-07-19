"""Audit log helper — call ``record_action`` from sensitive write paths.

Ported from ``services/cms/app/services/audit.py``. The FastAPI original is
async and takes an explicit ``AsyncSession``; Django's ORM is sync and the
request/response cycle here is sync too, so this is a straight synchronous
port with the same field mapping and call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from apps.cms.models import AuditLog


def record_action(
    request,
    *,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    changes: Optional[dict[str, Any]] = None,
) -> AuditLog:
    """Persist an audit entry for an admin CRUD action.

    Call from:
      * admin CRUD (create/update/delete)
      * auth events (login, logout, token refresh, OAuth connect/disconnect)
      * DLP blocks, rate-limit rejections

    ``request`` is the Django ``HttpRequest`` — used only to pull IP/user-agent
    /correlation-id, mirroring the FastAPI original's ``request`` parameter.
    """
    ip = request.META.get("REMOTE_ADDR") if request is not None else None
    user_agent = request.headers.get("user-agent") if request is not None else None
    correlation_id = getattr(request, "request_id", None) if request is not None else None

    return AuditLog.objects.create(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        changes=changes,
        ip_address=ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
