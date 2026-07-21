"""Audit-log helper — call ``record_action`` from privileged write paths.

Ported from ``services/requests/app/services/audit.py`` and aligned with the
platform's existing helpers (``apps.cms.services.audit``,
``apps.media_files.services.audit``): the request object is optional, and
when present it supplies ip / user-agent / correlation-id.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import AuditLog

logger = logging.getLogger(__name__)


def record_action(request=None, *, user_id: int | None, action: str,
                  resource_type: str, resource_id: Any = None,
                  changes: dict | None = None) -> AuditLog:
    ip = user_agent = correlation_id = None
    if request is not None:
        ip = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT")
        # RequestIDMiddleware stamps this; getattr keeps the helper usable
        # from a Celery task, where there is no request at all.
        correlation_id = getattr(request, "request_id", None)

    entry = AuditLog.objects.create(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        changes=changes,
        ip_address=ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    logger.info("audit_log_recorded action=%s resource=%s/%s user=%s",
                action, resource_type, entry.resource_id, user_id)
    return entry
