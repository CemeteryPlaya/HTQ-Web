"""HR service auth — re-exports the canonical primitives from htqweb_auth.

Kept as a thin shim so existing `from app.auth.dependencies import ...`
imports across the service don't all need touching at once.

``require_hr_write`` is HR-specific business logic: it gates on the coarse
``is_elevated`` flag (admin/staff/superuser).  It stays here rather than in
the shared package because it encodes a policy decision that belongs to this
service.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status

from htqweb_auth import (
    TokenPayload,
    get_current_user,
    get_optional_user,
    require_admin,
    security,
)

# Legacy role sets — kept for back-compat with code that still reads `role`.
HR_WRITE_ROLES = {"hr_admin", "hr_manager", "admin"}
HR_READ_ROLES = {"hr_admin", "hr_manager", "recruiter", "employee", "admin"}


def require_hr_write(
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
) -> TokenPayload:
    """Require admin/staff/superuser — coarse HR write gate.

    This is a transitional dependency.  Once the HR service adopts
    ``require_level(DepartmentLevel.MIDDLE, resolve_hr_level)`` from
    the shared package, this function can be retired.
    """
    if not current_user.is_elevated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user


__all__ = [
    "TokenPayload",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_hr_write",
    "security",
    "HR_WRITE_ROLES",
    "HR_READ_ROLES",
]
