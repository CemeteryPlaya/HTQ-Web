"""Mark-read endpoint."""
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.domain import RoomParticipant
from app.services.audit import record_action

router = APIRouter(tags=["read"])

@router.post("/messages/room/{room_id}/read/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    room_id: int,
    message_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> None:
    stmt = (
        update(RoomParticipant)
        .where(RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.user_id)
        .values(
            last_read_message_id=message_id,
        )
    )
    await session.execute(stmt)
    await session.commit()
    await record_action(session, user.user_id, "mark_read", "RoomParticipant", f"{room_id}/{message_id}")
