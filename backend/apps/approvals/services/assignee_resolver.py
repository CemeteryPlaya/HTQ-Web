"""Resolve a workflow node's ``assignee`` spec into concrete user ids.

Ported from ``services/requests/app/services/assignee_resolver.py``. The
pure kinds (``user``, ``users``, ``initiator``, ``field_ref``) come across
unchanged; the three that read other services are where decision Р2 bites.

* ``project_admins`` — was a query against the local ``request_project_members``
  table and still is: project membership is owned by THIS domain, so nothing
  changed.
* ``initiator_supervisor`` / ``department_head`` — was an S2S call to
  hr-service. Now ``apps.hr.interface``: the initiator's employee brief gives
  their department, and the department brief names its head. **The
  ``head_user_id`` key is an assumption that needs confirming with Поток A**
  (§7 fixes the function signatures, not the dict contents); if hr returns a
  different key, this is the one place to change.
* ``role`` — was ``SELECT id FROM request_users WHERE is_elevated``, i.e. a
  read of the user replica. With the replica gone there is no way to ask
  "who is elevated": the agreed users brief carries ``is_active`` but not
  role or elevation, and a consumer may not extend a neighbour's interface
  (PLAN.md §1.5 п.3). It raises with a message naming what is missing.

**Failure is loud on purpose, and differs from the §7 degradation rule.**
Elsewhere an unavailable neighbour costs enrichment; here it decides *who
must approve*. Silently routing to nobody would leave a request stuck with
no approver and no error, or — worse for a ``role`` node — approve nothing
while looking approved. So resolution failures raise, and the caller turns
them into a 4xx with the reason.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.services import ServiceDisabled
from apps.hr import interface as hr_interface

from ..models import ProjectMemberRole, RequestProjectMember

logger = logging.getLogger(__name__)


class AssigneeResolutionError(Exception):
    pass


def _supervisor_of(initiator_id: int) -> int:
    """Head of the initiator's department, via ``apps.hr.interface``."""
    try:
        employee = hr_interface.get_employee_brief(initiator_id)
        department_id = (employee or {}).get("department_id")
        if department_id is None:
            raise AssigneeResolutionError(
                f"no department known for user {initiator_id}")
        department = hr_interface.get_department_brief(department_id)
        head_id = (department or {}).get("head_user_id")
    except ServiceDisabled as exc:
        raise AssigneeResolutionError(
            "hr is disabled — cannot resolve the initiator's supervisor"
        ) from exc
    except NotImplementedError as exc:
        # apps.hr.interface is still the prep-4.0 stub (PLAN.md §6.3).
        raise AssigneeResolutionError(
            "hr interface is not implemented yet — cannot resolve the "
            "initiator's supervisor"
        ) from exc
    if head_id is None:
        raise AssigneeResolutionError(
            f"no supervisor / department head found for user {initiator_id}")
    return int(head_id)


def resolve_assignees(assignee: dict[str, Any] | None, *, initiator_id: int,
                      project_id: int | None,
                      form_values: dict | None = None) -> list[int]:
    if not assignee or "kind" not in assignee:
        raise AssigneeResolutionError("approval node missing assignee.kind")
    kind = assignee["kind"]

    if kind == "user":
        uid = assignee.get("id")
        if not isinstance(uid, int):
            raise AssigneeResolutionError("user assignee requires integer 'id'")
        return [uid]

    if kind == "users":
        ids = assignee.get("ids")
        if not isinstance(ids, list) or not ids \
                or not all(isinstance(x, int) for x in ids):
            raise AssigneeResolutionError(
                "users assignee requires a non-empty 'ids' list of ints")
        return ids

    if kind == "initiator":
        return [initiator_id]

    if kind == "project_admins":
        if project_id is None:
            raise AssigneeResolutionError(
                "project_admins assignee requires the request to have a project")
        return list(RequestProjectMember.objects.filter(
            project_id=project_id, role=ProjectMemberRole.ADMIN,
        ).values_list("user_id", flat=True))

    if kind == "role":
        raise AssigneeResolutionError(
            "assignee kind 'role' needs an elevated-users lookup in "
            "apps.users.interface (PLAN.md §7 contract extension, pending "
            "A↔B agreement) — the user replica it used to read is gone (Р2)")

    if kind == "field_ref":
        field = assignee.get("field")
        if not isinstance(field, str) or not field:
            raise AssigneeResolutionError(
                "field_ref assignee requires non-empty 'field'")
        if form_values is None or field not in form_values \
                or form_values[field] is None:
            raise AssigneeResolutionError(
                f"field_ref '{field}' missing from form_values")
        raw = form_values[field]
        if isinstance(raw, list):
            try:
                return [int(x) for x in raw]
            except (TypeError, ValueError):
                raise AssigneeResolutionError(
                    f"field_ref '{field}' contains non-int values")
        try:
            return [int(raw)]
        except (TypeError, ValueError):
            raise AssigneeResolutionError(
                f"field_ref '{field}' is not a user id")

    if kind in ("initiator_supervisor", "department_head"):
        # Both collapse to "head of the initiator's department" in this hr
        # model; they stay separate kinds so they can diverge if hr ever
        # grows a position-hierarchy supervisor distinct from the dept head.
        return [_supervisor_of(initiator_id)]

    raise AssigneeResolutionError(f"assignee kind '{kind}' is not supported")
