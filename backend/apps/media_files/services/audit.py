"""Audit log helper — call ``record_action`` from sensitive write paths.

Same shape as ``apps.cms.services.audit`` (each app owns its own concrete
``AuditLog`` model rather than sharing one — see ``apps.media_files.models
.AuditLog``'s docstring), ported from ``services/media/app/services/
audit.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.media_files.models import AuditLog

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
    """Persist an audit entry for a media mutation.

    **Non-fatal by construction (review fix-pass on R3):** the caller's
    primary mutation (e.g. the uploaded ``FileMetadata`` row) is already
    committed by the time this runs — an audit-insert failure must not 500
    an already-successful request. ``AuditLog.objects.create`` is wrapped in
    ``try/except Exception: logger.exception(...)`` here, once, so call
    sites stay simple (same pattern as ``apps.users.services.audit``/
    ``apps.cms.services.audit``). Returns ``None`` on a swallowed failure.
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
