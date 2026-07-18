"""Shared authentication primitives for HTQWeb microservices.

Public surface — importable directly from ``htqweb_auth``:

* ``AuthSettings`` / ``auth_settings`` / ``get_auth_settings`` — fail-fast JWT config.
* ``TokenPayload`` — canonical decoded JWT.
* ``security`` — preconfigured ``HTTPBearer`` (auto_error=False).
* ``get_current_user`` / ``get_optional_user`` — FastAPI dependencies.
* ``require_admin`` — coarse admin/staff/superuser gate.
* ``DepartmentLevel`` / ``require_level`` / ``LevelResolver`` — department-scoped levels.

Per-service code typically does::

    from htqweb_auth import TokenPayload, get_current_user, require_admin
"""

from .config import AuthSettings, auth_settings, get_auth_settings
from .dependencies import get_current_user, get_optional_user, security
from .levels import DepartmentLevel, LevelResolver, require_level
from .payload import TokenPayload
from .rbac import require_admin

__all__ = [
    # config
    "AuthSettings",
    "auth_settings",
    "get_auth_settings",
    # payload
    "TokenPayload",
    # dependencies
    "security",
    "get_current_user",
    "get_optional_user",
    # rbac
    "require_admin",
    # levels
    "DepartmentLevel",
    "LevelResolver",
    "require_level",
]
