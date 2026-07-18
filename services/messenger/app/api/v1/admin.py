"""Admin-only: список всех комнат, сообщения в комнате (для moderation audit)."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import TokenPayload, require_admin
from app.db import get_db_session
from app.models.domain import Room, Message
from app.services.history_archive import archive_recent_history

router = APIRouter(tags=["admin"])

@router.get("/rooms")
async def list_all_rooms(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
): 
    result = await session.execute(select(Room).offset(offset).limit(limit))
    return result.scalars().all()

@router.get("/rooms/{room_id}/messages")
async def list_messages_in_room(
    room_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
):
    result = await session.execute(
        select(Message)
        .where(Message.room_id == room_id)
        .options(selectinload(Message.sender), selectinload(Message.attachments))
    )
    return result.scalars().all()


@router.post("/history/archive")
async def trigger_history_archive(
    _admin: Annotated[TokenPayload, Depends(require_admin)],
    days: int = Query(7, ge=1, le=90),
):
    """Manually run the room-history archive (the scheduler does this every
    Saturday 04:30 GMT+5; this endpoint is for backfill / dev)."""
    return await archive_recent_history(days=days)
