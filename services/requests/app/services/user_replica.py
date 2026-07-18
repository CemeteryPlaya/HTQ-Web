"""Self-heal guard for the ``request_users`` replica.

Projects and project-members carry FK constraints to ``request_users`` (see
app/models/project.py, app/models/project_member.py). That table is normally
filled asynchronously from the ``user.upserted`` pub/sub feed
(app/workers/replica_sync.py) and seeded in bulk by the user-service
``rebuild_user_replicas`` bootstrap actor.

Before the acting user's row has landed — a fresh deploy where the bootstrap
wasn't run, or a brand-new user acting before their upsert event propagates —
an INSERT referencing them raises ForeignKeyViolationError. This guard inserts
a minimal placeholder row from the JWT claims so the write succeeds; the full
record (first/last name, etc.) overwrites it when the replica event arrives.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload
from app.models.user_replica import RequestUser


async def ensure_user_replica(session: AsyncSession, user: TokenPayload) -> RequestUser:
    """Guarantee a ``request_users`` row exists for the acting user.

    Idempotent: returns the existing row untouched if present (so we never
    clobber the richer pub/sub-synced record with sparse token data).
    """
    existing = await session.get(RequestUser, user.user_id)
    if existing is not None:
        return existing
    row = RequestUser(
        id=user.user_id,
        username=user.username or "",
        email=user.email or "",
        is_active=True,
        is_elevated=user.is_elevated,
    )
    session.add(row)
    await session.flush()
    return row
