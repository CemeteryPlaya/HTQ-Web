"""Email service auth — re-exports the canonical primitives from htqweb_auth.

Kept as a thin shim so existing `from app.auth.dependencies import ...`
imports across the service don't all need touching at once.
"""
from htqweb_auth import (
    TokenPayload,
    get_current_user,
    get_optional_user,
    require_admin,
    security,
)

__all__ = [
    "TokenPayload",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "security",
]
