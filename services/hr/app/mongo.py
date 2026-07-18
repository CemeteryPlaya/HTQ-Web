"""MongoDB async client for HR service.

Provides a singleton Motor client and convenience accessors for
the ``hr_documents`` collection used to store bulky / unstructured
employee files that don't fit neatly into the relational schema.

The ``mongo_uri`` setting is optional — when empty the module exposes
``None`` so callers can gracefully fall back to SQL-only mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.settings import settings

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ── Singleton client ────────────────────────────────────────────────────────
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_mongo_client() -> AsyncIOMotorClient | None:
    """Return the Motor client, creating it lazily on first call."""
    global _client
    if _client is None and settings.mongo_uri:
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_mongo_db() -> AsyncIOMotorDatabase | None:
    """Return the default database handle."""
    global _db
    if _db is None:
        client = get_mongo_client()
        if client is not None:
            _db = client[settings.mongo_db_name]
    return _db


def get_hr_documents_collection() -> "AsyncIOMotorCollection | None":
    """Shortcut — returns the ``hr_documents`` collection or ``None``."""
    db = get_mongo_db()
    return db["hr_documents"] if db is not None else None


def get_hr_groups_collection() -> "AsyncIOMotorCollection | None":
    """Returns the ``hr_employee_groups`` collection or ``None``."""
    db = get_mongo_db()
    return db["hr_employee_groups"] if db is not None else None


async def close_mongo() -> None:
    """Shut down the Motor client (call from lifespan shutdown)."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


async def ensure_indexes() -> None:
    """Create MongoDB indexes on first startup (idempotent)."""
    coll = get_hr_documents_collection()
    if coll is None:
        return
    await coll.create_index("sql_employee_id")
    await coll.create_index("doc_type")
    await coll.create_index([("sql_employee_id", 1), ("doc_type", 1)])
    await coll.create_index("created_at")
    gcoll = get_hr_groups_collection()
    if gcoll is not None:
        await gcoll.create_index("employee_id", unique=True)
