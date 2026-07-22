"""Batched cross-app lookups for the approvals domain.

Same shape and the same reasoning as ``apps.tasks.services.hydration`` (read
its docstring for the full argument): collect ids first, one interface call,
then build responses — a per-row lookup would be an N+1 across an app
boundary, which is exactly the cost the deleted replicas existed to avoid.

Degradation follows PLAN.md §7: ``ServiceDisabled``, ``NotImplementedError``
(``apps.hr.interface`` is still the prep-4.0 stub) and any other neighbour
error cost the enrichment, never the request.

**One deliberate exception, and it is the important one.**
``assignee_resolver`` does NOT degrade — see its docstring. Enrichment
answers "what is this person called"; assignee resolution answers "who must
approve this". Quietly resolving nobody would strand a request with no
approver and no error, so that path raises instead.
"""

from __future__ import annotations

import logging
from typing import Iterable

from apps.core.services import ServiceDisabled
from apps.hr import interface as hr_interface
from apps.users import interface as users_interface

logger = logging.getLogger(__name__)


def _safe(call, what: str, default):
    try:
        return call()
    except ServiceDisabled:
        logger.debug("approvals: %s skipped, neighbour disabled", what)
        return default
    except NotImplementedError:
        logger.debug("approvals: %s skipped, interface still a prep stub", what)
        return default
    except Exception:
        logger.exception("approvals: %s failed, continuing without enrichment",
                         what)
        return default


def user_briefs(user_ids: Iterable[int | None]) -> dict[int, dict]:
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return {}
    rows = _safe(lambda: users_interface.get_users_brief(ids),
                 "users.get_users_brief", [])
    return {row["id"]: row for row in rows}


def department_briefs(department_ids: Iterable[int | None]) -> dict[int, dict]:
    ids = sorted({int(did) for did in department_ids if did is not None})
    if not ids:
        return {}
    rows = _safe(lambda: hr_interface.get_departments_brief(ids),
                 "hr.get_departments_brief", [])
    return {row["id"]: row for row in rows if row.get("id") is not None}


def user_name(briefs: dict[int, dict], user_id: int | None) -> str | None:
    if user_id is None:
        return None
    brief = briefs.get(int(user_id))
    return brief.get("full_name") if brief else None


def department_name(briefs: dict[int, dict],
                    department_id: int | None) -> str | None:
    if department_id is None:
        return None
    brief = briefs.get(int(department_id))
    return brief.get("name") if brief else None


def employee_department_id(user_id: int) -> int | None:
    """The user's HR department, or ``None`` when hr cannot answer.

    Single-id by nature (it resolves the caller, once per request). ``None``
    on degradation narrows what a caller sees rather than widening it — every
    visibility rule treats a missing department as "no department-wide grant".
    """
    brief = _safe(lambda: hr_interface.get_employee_brief(user_id),
                  "hr.get_employee_brief", None)
    return brief.get("department_id") if brief else None
