"""User Replica API endpoints.

Two flavours of endpoint live here:

- Internal ``/ingest`` for the user-service replication worker.
- Front-facing ``/me`` and ``/search`` used by the chat UI when the operator
  opens the "new conversation" picker. Both read from the local
  ``ChatUserReplica`` table — no cross-service joins.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user, require_admin
from app.db import get_db_session
from app.models.domain import ChatUserReplica
from app.schemas.messenger import UserReplicaRead

router = APIRouter(tags=["users"])


# ─── Internal: replica ingestion ────────────────────────────────────────────

@router.post("/ingest", response_model=UserReplicaRead, status_code=status.HTTP_201_CREATED)
async def ingest_user_replica(
    data: UserReplicaRead,
    session: AsyncSession = Depends(get_db_session),
    # In a real system, this should be secured by an internal service-to-service auth token
    # For now, require admin
    admin: TokenPayload = Depends(require_admin),
):
    """Ingest user data from the central user-service."""
    values = data.model_dump(exclude={"full_name", "user_id"})
    replica = await session.get(ChatUserReplica, data.id)
    if replica:
        # Update existing
        for k, v in values.items():
            setattr(replica, k, v)
    else:
        # Create new
        replica = ChatUserReplica(**values)
        session.add(replica)

    await session.commit()
    await session.refresh(replica)
    return replica


# ─── Front-facing ──────────────────────────────────────────────────────────


@router.get("/me/", response_model=UserReplicaRead)
@router.get("/me", response_model=UserReplicaRead)
async def me(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> UserReplicaRead:
    """Return the current user's replica row.

    If the replica hasn't been backfilled yet (e.g., a brand-new user that
    the replication worker hasn't ingested), build a minimal placeholder
    from the JWT claims so the UI doesn't 404 — the messenger frontend
    only needs ``id`` / ``username`` / display name to render the chrome.
    """
    replica = await session.get(ChatUserReplica, user.user_id)
    if replica is not None:
        return UserReplicaRead.model_validate(replica)

    return UserReplicaRead(
        id=user.user_id,
        username=user.username or user.email or f"user-{user.user_id}",
        first_name="",
        last_name="",
        avatar_url=None,
        is_active=True,
    )


@router.get("/search/", response_model=list[UserReplicaRead])
@router.get("/search", response_model=list[UserReplicaRead])
async def search_users(
    q: str = Query("", description="Free-text search across username/first/last"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> list[UserReplicaRead]:
    """Search the local user replicas for the chat picker.

    Empty/whitespace ``q`` returns the first ``limit`` active users so the
    picker has *something* on first open instead of an empty list. Searches
    are case-insensitive across ``username``, ``first_name``, ``last_name``.
    The current user is filtered out — you can't start a chat with yourself.
    """
    needle = (q or "").strip()
    stmt = select(ChatUserReplica).where(
        ChatUserReplica.is_active.is_(True),
        ChatUserReplica.id != user.user_id,
        # Bots are owned by the platform and addressed automatically — they
        # must not appear in the "start a new chat" picker.
        ChatUserReplica.is_bot.is_(False),
    )
    if needle:
        like = f"%{needle.lower()}%"
        stmt = stmt.where(
            or_(
                ChatUserReplica.username.ilike(like),
                ChatUserReplica.first_name.ilike(like),
                ChatUserReplica.last_name.ilike(like),
            )
        )
    stmt = stmt.order_by(ChatUserReplica.last_name, ChatUserReplica.first_name).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [UserReplicaRead.model_validate(r) for r in rows]
