"""Role-based access checks.

Ported from ``libs/htqweb_auth/rbac.py``. The original exposed a single
FastAPI dependency, ``require_admin(user: Annotated[TokenPayload,
Depends(get_current_user)])``, which resolved the current user itself (via
``get_current_user``) and raised ``HTTPException(403)`` on failure.

Neither of those two responsibilities is portable as-is:
- resolving "who is the current user" from a request is done by Django's
  ``api_view`` wrapper (Task 0.4), not by this module;
- turning a failed check into an HTTP response is likewise ``api_view``'s
  job, so it can pick the right response shape for Django views.

What's ported here is the pure predicate the FastAPI dependency was built
on top of: given an already-decoded ``TokenPayload``, is the caller
admin/staff/superuser? ``api_view`` (or a future decorator) is expected to
call this and raise/return its own 403 when it's ``False``.
"""

from __future__ import annotations

from .payload import TokenPayload


def require_admin(user: TokenPayload) -> bool:
    """True when ``user`` holds the coarse admin/staff/superuser flag."""
    return user.is_elevated
