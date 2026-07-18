"""Resolve a workflow node's ``assignee`` spec into concrete user ids.

Phase 3a supports ``user`` and ``project_admins``. Other kinds raise
``AssigneeResolutionError`` (added in Phase 4)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.models.user_replica import RequestUser


class AssigneeResolutionError(Exception):
    pass


async def resolve_assignees(
    session: AsyncSession,
    assignee: dict[str, Any] | None,
    *,
    initiator_id: int,
    project_id: int | None,
    form_values: dict | None = None,
) -> list[int]:
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
        if not isinstance(ids, list) or not ids or not all(isinstance(x, int) for x in ids):
            raise AssigneeResolutionError("users assignee requires a non-empty 'ids' list of ints")
        return ids

    if kind == "initiator":
        return [initiator_id]

    if kind == "project_admins":
        if project_id is None:
            raise AssigneeResolutionError("project_admins assignee requires the request to have a project")
        stmt = select(RequestProjectMember.user_id).where(
            RequestProjectMember.project_id == project_id,
            RequestProjectMember.role == ProjectMemberRole.ADMIN,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)

    if kind == "role":
        # Phase 4a: "role" maps to the platform's elevated flag. A finer-grained
        # role-string filter lands when user-service exposes a role catalog.
        stmt = select(RequestUser.id).where(RequestUser.is_elevated.is_(True))
        return list((await session.execute(stmt)).scalars().all())

    if kind == "field_ref":
        field = assignee.get("field")
        if not isinstance(field, str) or not field:
            raise AssigneeResolutionError("field_ref assignee requires non-empty 'field'")
        if form_values is None or field not in form_values or form_values[field] is None:
            raise AssigneeResolutionError(f"field_ref '{field}' missing from form_values")
        raw = form_values[field]
        if isinstance(raw, list):
            try:
                return [int(x) for x in raw]
            except (TypeError, ValueError):
                raise AssigneeResolutionError(f"field_ref '{field}' contains non-int values")
        try:
            return [int(raw)]
        except (TypeError, ValueError):
            raise AssigneeResolutionError(f"field_ref '{field}' is not a user id")

    if kind in ("initiator_supervisor", "department_head"):
        # Both collapse to "head of initiator's department" in our hr model.
        # Future: if hr grows a separate position-hierarchy supervisor, the two
        # kinds can diverge to different endpoints.
        from app.services.hr_client import HrS2SError, fetch_supervisor_user_id
        try:
            supervisor_id = await fetch_supervisor_user_id(initiator_id)
        except HrS2SError as exc:
            raise AssigneeResolutionError(f"hr-service lookup failed: {exc}")
        if supervisor_id is None:
            raise AssigneeResolutionError(
                f"no supervisor / department head found for user {initiator_id}"
            )
        return [int(supervisor_id)]

    raise AssigneeResolutionError(f"assignee kind '{kind}' is not supported")
