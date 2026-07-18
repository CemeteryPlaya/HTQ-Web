"""Role-based access dependencies.

Currently exposes only ``require_admin``, which guards endpoints behind the
coarse ``is_elevated`` flag (admin / staff / superuser). Department-scoped
checks live in ``levels.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from .dependencies import get_current_user
from .payload import TokenPayload


def require_admin(
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> TokenPayload:
    """Allow only callers with admin/staff/superuser flag set."""
    if not user.is_elevated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
