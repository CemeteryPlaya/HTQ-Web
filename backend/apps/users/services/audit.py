"""Audit log helper — call ``record_action`` from sensitive write paths.

Same shape as ``apps.cms.services.audit`` / ``apps.media_files.services.
audit`` (each app owns its own concrete ``AuditLog`` model rather than
sharing one — see ``apps.users.models.AuditLog``'s docstring).

Call from the identity domain's privileged mutations (R3 remediation task):

* ``user.created`` — admin-created user (``apps.users.views._admin_create_user``)
* ``user.updated`` — admin partial update, ``changes`` is a diff of the
  fields whose value actually changed, including privilege flags
  (``is_staff``/``is_superuser``/``status``) (``_admin_update_user``)
* ``user.password_set`` — admin-initiated password reset; ``changes`` never
  carries the password/hash, only that it happened + the resulting
  ``must_change_password`` flag (``admin_set_password``)
* ``user.suspended`` — admin soft-delete (status -> SUSPENDED)
  (``_admin_delete_user``)
* ``registration.approved`` / ``registration.rejected`` — moderation of a
  pending self-registration (``approve_registration``/``reject_registration``)

``request`` is the Django ``HttpRequest`` — used only to pull IP/user-agent/
correlation-id, mirroring the cms/media originals' ``request`` parameter.
"""

from __future__ import annotations

from typing import Any, Optional

from apps.users.models import AuditLog


def record_action(
    request,
    *,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    changes: Optional[dict[str, Any]] = None,
) -> AuditLog:
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
