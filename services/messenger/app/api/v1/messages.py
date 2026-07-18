"""Message API endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.domain import ChatAttachment, Message, RoomParticipant
from app.schemas.messenger import MessageCreate, MessageRead
from app.services.messenger_service import MessengerService

router = APIRouter(tags=["messages"])


@router.post("/", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def send_message(
    data: MessageCreate,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    service = MessengerService(session)
    try:
        msg = await service.send_message(data, sender_id=user.user_id)
        return msg
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/room/{room_id}", response_model=list[MessageRead])
async def list_messages(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Free-text substring (case-insensitive)"),
    data_type: Literal["images", "audio", "documents", "video"] | None = Query(
        None, description="Restrict to messages that own at least one attachment of this kind"
    ),
    since: datetime | None = Query(None, description="Only messages created on/after this ISO timestamp"),
    until: datetime | None = Query(None, description="Only messages created strictly before this ISO timestamp"),
):
    """List messages in a room, optionally filtered by text/date/attachment kind.

    Search uses simple ``ILIKE`` on the stored content (a JSON blob for
    most rooms, so the match hits both the body and the optional caption
    of file/voice/image messages). For E2EE rooms the encrypted ciphertext
    won't decode to plain text on the server — text search there is a
    no-op by design; the client falls back to local-side filtering.
    """
    rp = await session.get(RoomParticipant, (room_id, user.user_id))
    if not rp:
        raise HTTPException(status_code=403, detail="Not a participant")

    stmt = (
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .options(selectinload(Message.sender), selectinload(Message.attachments))
    )
    if q:
        from sqlalchemy import or_

        pattern = f"%{q.strip()}%"
        # Match either the body (JSON string `{"text": "..."}`) or any of
        # the attached files' display names. Lets the user find an image
        # by typing part of its filename.
        stmt = stmt.where(
            or_(
                Message.content.ilike(pattern),
                exists().where(
                    and_(
                        ChatAttachment.message_id == Message.id,
                        ChatAttachment.filename.ilike(pattern),
                    )
                ),
            )
        )
    if since is not None:
        stmt = stmt.where(Message.created_at >= since)
    if until is not None:
        stmt = stmt.where(Message.created_at < until)
    if data_type:
        stmt = stmt.where(
            exists().where(
                and_(
                    ChatAttachment.message_id == Message.id,
                    ChatAttachment.data_type == data_type,
                )
            )
        )

    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/room/{room_id}/read/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def mark_message_read(
    room_id: int,
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    service = MessengerService(session)
    try:
        await service.mark_read(room_id, message_id, user.user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/room/{room_id}/typing", status_code=status.HTTP_204_NO_CONTENT)
async def publish_typing(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    service = MessengerService(session)
    await service.publish_typing(room_id, user.user_id)
