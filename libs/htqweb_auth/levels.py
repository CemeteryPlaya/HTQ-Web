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
profile / position / department. ``require_level`` here only enforces the
ordering once the level has been resolved.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status

from .dependencies import get_current_user
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
# (HR profile, position string, department membership, etc.). The shared
# package only orchestrates the comparison — the *answer* about who is
# what level is service-specific business logic.
LevelResolver = Callable[[TokenPayload], DepartmentLevel]


def require_level(
    minimum: DepartmentLevel,
    resolver: LevelResolver,
) -> Callable[..., TokenPayload]:
    """Build a FastAPI dependency that enforces ``minimum`` level.

    Usage in a service::

        from htqweb_auth import DepartmentLevel, require_level
        from app.auth.hr_access import resolve_hr_level

        require_hr_senior = require_level(DepartmentLevel.SENIOR, resolve_hr_level)

        @router.get("/sensitive")
        def handler(user = Depends(require_hr_senior)):
            ...

    The dependency runs ``get_current_user`` first (so 401 still happens for
    unauthenticated callers), then defers to ``resolver`` for the
    department-aware level computation. ``is_elevated`` users always pass —
    a global admin should never be locked out by a department check.
    """

    def _dep(
        user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        if user.is_elevated:
            return user
        actual = resolver(user)
        if not actual.meets(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum.value} or higher (have {actual.value})",
            )
        return user

    return _dep
