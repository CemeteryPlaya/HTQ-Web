"""Per-provider mailbox sync drivers.

Selection happens in :func:`get_driver` so callers (Dramatiq actors,
the manual ``POST /accounts/{id}/sync/`` endpoint) stay flat.
"""

from app.services.sync.base import SyncDriver, SyncResult
from app.services.sync.factory import get_driver

__all__ = ["SyncDriver", "SyncResult", "get_driver"]
