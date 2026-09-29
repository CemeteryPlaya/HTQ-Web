"""Batched cross-app lookups for denormalised response fields.

This module is the whole of decision Р2 in one place. The FastAPI original
kept local replica tables (``task_users``, ``task_departments``) synced over
Redis pub/sub, so ``assignee_name`` / ``department_name`` were a JOIN away.
Those replicas are gone (see ``apps.tasks.models``' docstring); the same
fields are now filled by calling the owning app's ``interface``.

Two properties this module must have, and the reasons they are not optional:

**Batched.** Every entry point takes a collection of ids and issues ONE
interface call. A per-row lookup would be an N+1 across an app boundary —
the exact cost the replicas existed to avoid. Callers collect ids first,
hydrate once, then build responses from the returned maps.

**Degrading.** PLAN.md §7 makes graceful degradation a hard requirement for
interface consumers: if the neighbour is disabled the enrichment is dropped,
never the request. Three failure modes are swallowed here, deliberately:

* ``ServiceDisabled`` — the neighbour is switched off in the registry. A
  task list must still render (without department chips) rather than 503;
  the tasks service itself is up, and its own gate already ran.
* ``NotImplementedError`` — ``apps.hr.interface`` is still the prep-4.0 stub
  (Поток A implements it in phase 6, PLAN.md §6.3). Coding against the
  agreed signature and degrading until the real body lands is exactly the
  arrangement §4.2 describes; when hr lands, these calls start returning
  data with no change here.
* Any other exception — logged, then dropped. A neighbour's bug must not
  become this domain's 500.

Known gap, needs A↔B coordination (PLAN.md §7, §1.5 п.3): the response
schemas carry ``avatar_url`` for assignees/delegates/watchers, but the agreed
``apps.users.interface`` brief is ``{id, username, email, full_name,
is_active}`` — no avatar. ``apps.users.models.User.avatar_url`` exists, but a
consumer may not reach past the interface (``test_app_isolation.py``), and
extending someone else's interface unilaterally is forbidden. Until that
signature is extended by agreement, ``avatar_url`` hydrates to ``None``.
Notifications are unaffected: they carry their own ``actor_avatar_url``
snapshot column, which is a point-in-time record rather than a live lookup.
"""

from __future__ import annotations

import logging
from typing import Iterable

from apps.core.services import ServiceDisabled
from apps.hr import interface as hr_interface
from apps.users import interface as users_interface

logger = logging.getLogger(__name__)


def _safe(call, what: str, default):
    """Run a neighbour's interface call, degrading instead of propagating.

    See the module docstring for why each of these is swallowed.
    """
    try:
        return call()
    except ServiceDisabled:
        # Expected and routine — the neighbour is switched off.
        logger.debug("tasks: %s skipped, neighbour disabled", what)
        return default
    except NotImplementedError:
        # Expected until Поток A fills the stub (PLAN.md §6.3).
        logger.debug("tasks: %s skipped, interface still a prep stub", what)
        return default
    except Exception:
        logger.exception("tasks: %s failed, continuing without enrichment", what)
        return default


def user_briefs(user_ids: Iterable[int | None]) -> dict[int, dict]:
    """Map ``user_id -> brief`` for the ids that resolve.

    Unknown/deleted ids are simply absent (the interface's documented
    "unknown -> omitted" contract), so callers use ``.get(id)`` and render
    ``None`` — the same output the original produced from a lagging replica.
    """
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return {}
    rows = _safe(lambda: users_interface.get_users_brief(ids),
                 "users.get_users_brief", [])
    return {row["id"]: row for row in rows}


def department_briefs(department_ids: Iterable[int | None]) -> dict[int, dict]:
    """Map ``department_id -> brief`` for the ids hr can resolve."""
    ids = sorted({int(did) for did in department_ids if did is not None})
    if not ids:
        return {}
    rows = _safe(lambda: hr_interface.get_departments_brief(ids),
                 "hr.get_departments_brief", [])
    return {row["id"]: row for row in rows if row.get("id") is not None}


def user_name(briefs: dict[int, dict], user_id: int | None) -> str | None:
    """Display name for a user id, or ``None`` if it did not resolve.

    ``full_name`` is what ``apps.users.interface`` computes (first+last with
    a display_name/username fallback) — the original's
    ``"{first_name} {last_name}".strip() or username`` by another name, so
    the rendered string is unchanged.
    """
    if user_id is None:
        return None
    brief = briefs.get(int(user_id))
    return brief.get("full_name") if brief else None


def user_avatar(briefs: dict[int, dict], user_id: int | None) -> str | None:
    """Avatar URL for a user id.

    Always ``None`` today — see the "Known gap" paragraph in the module
    docstring. Kept as a named function (rather than inlining ``None`` at
    every call site) so that extending the users brief is a one-line change
    here instead of a hunt through the response builders.
    """
    if user_id is None:
        return None
    brief = briefs.get(int(user_id))
    return brief.get("avatar_url") if brief else None


def employee_department_id(user_id: int) -> int | None:
    """The user's HR department, or ``None`` when hr cannot answer.

    Single-id by nature (it resolves the *caller*, once per request), so
    unlike the rest of this module it is not batched.

    ``None`` on degradation is safe here rather than merely lossy: every
    visibility rule in ``task_service`` treats a missing department as "no
    department-wide grant", so a disabled hr narrows what the caller sees
    instead of widening it.
    """
    brief = _safe(lambda: hr_interface.get_employee_brief(user_id),
                  "hr.get_employee_brief", None)
    return brief.get("department_id") if brief else None


def department_name(briefs: dict[int, dict], department_id: int | None) -> str | None:
    if department_id is None:
        return None
    brief = briefs.get(int(department_id))
    return brief.get("name") if brief else None
