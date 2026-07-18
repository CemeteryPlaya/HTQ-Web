"""Room API endpoints."""


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sqlalchemy import and_, func, or_

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.domain import Message, Room, RoomParticipant
from app.schemas.messenger import MessageRead, RoomCreate, RoomRead, RoomUpdate
from app.services.messenger_service import MessengerService

router = APIRouter(tags=["rooms"])


async def _unread_counts_for(
    session: AsyncSession, *, user_id: int, room_ids: list[int]
) -> dict[int, int]:
    """Count unread messages per room for the given user.

    Unread = messages in the room not authored by the user that landed AFTER
    the user's ``last_read_message_id`` (or all such messages when nothing
    has been read yet). Computed in a single query so the rooms list stays
    cheap regardless of room/message volume.
    """
    if not room_ids:
        return {}

    # Self-join so we can resolve last_read_message_id → its created_at.
    LastRead = Message.__table__.alias("last_read")
    rp = RoomParticipant.__table__
    msgs = Message.__table__

    stmt = (
        select(rp.c.room_id, func.count(msgs.c.id))
        .select_from(
            rp.outerjoin(LastRead, LastRead.c.id == rp.c.last_read_message_id)
            .outerjoin(
                msgs,
                and_(
                    msgs.c.room_id == rp.c.room_id,
                    msgs.c.sender_id != rp.c.user_id,
                    or_(
                        rp.c.last_read_message_id.is_(None),
                        msgs.c.created_at > LastRead.c.created_at,
                    ),
                ),
            )
        )
        .where(rp.c.user_id == user_id, rp.c.room_id.in_(room_ids))
        .group_by(rp.c.room_id)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1] or 0) for row in result.all()}


async def _attach_last_messages(session: AsyncSession, rooms: list[Room]) -> dict[int, MessageRead]:
    """Fetch the latest message per room in a single query.

    Postgres ``DISTINCT ON`` is the cleanest way to grab one row per group:
    ``SELECT DISTINCT ON (room_id) ... ORDER BY room_id, created_at DESC``.
    Eager-loading the relationship would pull every message, which is wasteful
    when the room list only renders a single preview line per room.
    """
    if not rooms:
        return {}
    room_ids = [r.id for r in rooms]
    stmt = (
        select(Message)
        .where(Message.room_id.in_(room_ids))
        .order_by(Message.room_id, desc(Message.created_at))
        .distinct(Message.room_id)
        .options(selectinload(Message.sender), selectinload(Message.attachments))
    )
    result = await session.execute(stmt)
    out: dict[int, MessageRead] = {}
    for msg in result.scalars().all():
        out[msg.room_id] = MessageRead.model_validate(msg)
    return out


def _serialize_room(
    room: Room,
    *,
    last_messages: dict[int, MessageRead],
    unread_for_user: dict[int, int] | None = None,
    me_user_id: int | None = None,
) -> RoomRead:
    payload = RoomRead.model_validate(room)
    payload.last_message = last_messages.get(room.id)
    if me_user_id is not None and unread_for_user is not None:
        unread = unread_for_user.get(room.id, 0)
        for p in payload.participants:
            if p.user_id == me_user_id:
                p.unread_count = unread
                break
    return payload


@router.post("/", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RoomCreate,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    service = MessengerService(session)
    try:
        room = await service.create_room(data, creator_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stmt = (
        select(Room)
        .where(Room.id == room.id)
        .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
    )
    result = await session.execute(stmt)
    fresh = result.scalar_one()
    return _serialize_room(fresh, last_messages={}, me_user_id=user.user_id)


@router.get("/", response_model=list[RoomRead])
async def list_user_rooms(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """List rooms the current user is a participant of."""
    stmt = (
        select(Room)
        .join(RoomParticipant)
        .where(RoomParticipant.user_id == user.user_id)
        .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
    )
    result = await session.execute(stmt)
    rooms = list(result.scalars().all())
    last_messages = await _attach_last_messages(session, rooms)
    unread = await _unread_counts_for(
        session, user_id=user.user_id, room_ids=[r.id for r in rooms]
    )
    return [
        _serialize_room(
            r,
            last_messages=last_messages,
            unread_for_user=unread,
            me_user_id=user.user_id,
        )
        for r in rooms
    ]


@router.get("/{room_id}", response_model=RoomRead)
async def get_room(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Get details of a specific room."""
    # Check if user is in room
    rp = await session.get(RoomParticipant, (room_id, user.user_id))
    if not rp:
        raise HTTPException(status_code=403, detail="Not a participant")

    stmt = select(Room).where(Room.id == room_id).options(
        selectinload(Room.participants).selectinload(RoomParticipant.user)
    )
    result = await session.execute(stmt)
    room = result.scalar_one_or_none()

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return room


@router.patch("/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: int,
    data: RoomUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Update a group room's display fields (name / avatar_url).

    Only ``group`` rooms are editable: direct chats derive their name and
    avatar from the other participant, and editing a secret-chat title
    would leak metadata. The caller must be an ``admin`` participant.
    """
    rp = await session.get(RoomParticipant, (room_id, user.user_id))
    if not rp:
        raise HTTPException(status_code=403, detail="Not a participant")
    if rp.role != "admin":
        raise HTTPException(status_code=403, detail="Only room admins can edit")

    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.room_type != "group":
        raise HTTPException(
            status_code=400,
            detail="Only group rooms support name/avatar editing",
        )

    if data.name is not None:
        room.name = data.name.strip() or None
    if data.avatar_url is not None:
        # Empty string clears the photo; non-empty stores the signed URL.
        room.avatar_url = data.avatar_url.strip() or None

    await session.commit()

    stmt = (
        select(Room)
        .where(Room.id == room_id)
        .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
    )
    fresh = (await session.execute(stmt)).scalar_one()
    return _serialize_room(fresh, last_messages={}, me_user_id=user.user_id)
