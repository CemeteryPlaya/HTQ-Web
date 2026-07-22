"""Authorization helpers for the approvals domain.

Ported from ``services/requests/app/auth/permissions.py``. Two rules, and the
asymmetry between them is deliberate:

* a **project** may be managed by a global admin or by an admin member of
  that project;
* a **global template** (``project_id is None``) requires a global admin —
  a project admin may not create forms that apply platform-wide.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from ..models import ProjectMemberRole, RequestProjectMember


def is_project_admin(project_id: int, user_id: int) -> bool:
    return RequestProjectMember.objects.filter(
        project_id=project_id, user_id=user_id,
        role=ProjectMemberRole.ADMIN,
    ).exists()


def ensure_can_manage_project(project_id: int, token) -> None:
    if token.is_elevated:
        return
    if is_project_admin(project_id, token.user_id):
        return
    raise PermissionDenied("Not allowed to manage this project")


def ensure_can_manage_template(project_id: int | None, token) -> None:
    if token.is_elevated:
        return
    if project_id is None:
        raise PermissionDenied("Only elevated admins manage global templates")
    if is_project_admin(project_id, token.user_id):
        return
    raise PermissionDenied("Not allowed to manage templates for this project")
