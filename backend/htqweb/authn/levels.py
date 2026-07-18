"""Department-scoped access levels.

A *level* describes the seniority a user holds **inside their department**.
The level is intentionally orthogonal to which department the user belongs
to — the latter is carried separately (``employee.department_id`` on the HR
side). That keeps the enum free of names like ``co_hr`` / ``co_finance`` and
lets the same enum apply to every department past, present, and future.

Mapping convention (HR is the canonical case, others follow):

* ``junior``  — read-only inside own department
* ``middle``  — basic write inside own department
* ``senior``  — write across all departments (no destructive ops)
* ``lead``    — full control of own department; admin/staff treated as
                ``lead`` of every department for back-compat with current
                global-admin behaviour

Per-service ``*_access.py`` helpers translate user → level by looking at HR
profile / position / department. ``meets_level`` here only enforces the
ordering once the level has been resolved.

Ported from ``libs/htqweb_auth/levels.py``. ``DepartmentLevel`` (the enum,
``rank``, ``meets``) is pure logic and is copied unchanged. The original
also exposed ``require_level``, a FastAPI dependency *builder* that wrapped
``Depends(get_current_user)`` and raised ``HTTPException(403)``. Like
``rbac.require_admin``, resolving the current user and shaping the HTTP
error is Django ``api_view``'s job (Task 0.4), so that part is not ported.
What's kept is the plain comparison ``require_level`` delegated to
internally: given an already-decoded user, does its resolved level meet the
minimum (or is it globally elevated)? See ``meets_level`` below.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from .payload import TokenPayload


class DepartmentLevel(str, Enum):
    """Ordered seniority levels. Comparison via ``rank`` (see below)."""

    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"

    @property
    def rank(self) -> int:
        """Numeric ordering — higher ⇒ more privileges. Used by ``meets``."""
        return _RANK[self]

    def meets(self, minimum: "DepartmentLevel") -> bool:
        """True when ``self`` is at least as privileged as ``minimum``."""
        return self.rank >= minimum.rank


_RANK: dict[DepartmentLevel, int] = {
    DepartmentLevel.JUNIOR: 0,
    DepartmentLevel.MIDDLE: 1,
    DepartmentLevel.SENIOR: 2,
    DepartmentLevel.LEAD: 3,
}


# Type alias: a service-side resolver that maps a decoded token to the
# caller's level. Each service implements this on top of its own data
# (HR profile, position string, department membership, etc.). This module
# only orchestrates the comparison — the *answer* about who is what level
# is service-specific business logic.
LevelResolver = Callable[[TokenPayload], DepartmentLevel]


def meets_level(user: TokenPayload, minimum: DepartmentLevel,
                resolver: LevelResolver) -> bool:
    """True when ``user`` meets ``minimum`` department level.

    ``is_elevated`` users always pass — a global admin should never be
    locked out by a department check. Otherwise defers to ``resolver`` for
    the department-aware level computation, mirroring the original
    ``require_level`` FastAPI dependency minus the request-resolution and
    HTTP-error parts (now ``api_view``'s responsibility, Task 0.4).
    """
    if user.is_elevated:
        return True
    return resolver(user).meets(minimum)
