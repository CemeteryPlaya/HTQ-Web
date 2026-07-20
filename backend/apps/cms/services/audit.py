"""Audit log helper — call ``record_action`` from sensitive write paths.

Ported from ``services/cms/app/services/audit.py``. The FastAPI original is
async and takes an explicit ``AsyncSession``; Django's ORM is sync and the
request/response cycle here is sync too, so this is a straight synchronous
port with the same field mapping and call sites.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.cms.models import AuditLog

logger = logging.getLogger(__name__)


def record_action(
    request,
    *,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    changes: Optional[dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """Persist an audit entry for an admin CRUD action.

    Call from:
      * admin CRUD (create/update/delete)
      * auth events (login, logout, token refresh, OAuth connect/disconnect)
      * DLP blocks, rate-limit rejections

    ``request`` is the Django ``HttpRequest`` — used only to pull IP/user-agent
    /correlation-id, mirroring the FastAPI original's ``request`` parameter.

    **Non-fatal by construction (review fix-pass on R3):** every call site
    above calls this AFTER the primary mutation already committed (autocommit)
    — an audit-insert failure must not 500 an already-successful request.
    ``AuditLog.objects.create`` is wrapped in ``try/except Exception:
    logger.exception(...)`` here, once, so call sites stay simple (same
    pattern as ``apps.users.services.audit``/``apps.media_files.services.
    audit``). Returns ``None`` on a swallowed failure.
    """
    ip = request.META.get("REMOTE_ADDR") if request is not None else None
    user_agent = request.headers.get("user-agent") if request is not None else None
    correlation_id = getattr(request, "request_id", None) if request is not None else None

    try:
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
    except Exception:
        logger.exception(
            "audit record_action failed action=%s resource_type=%s resource_id=%s",
            action, resource_type, resource_id,
        )
        return None
