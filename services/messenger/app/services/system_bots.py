"""System bot replicas and bot-DM helpers.

5 system bots live alongside real users in ``chat_user_replicas`` so the
existing chat / room / Socket.IO pipeline carries their messages too —
no parallel data model.

IDs are picked from a range that real ``user-service`` ids will never
reach (``9_000_001+``), so accidental collision is impossible. Each bot
has a hard-coded display name + emoji; the frontend renders an extra
``BOT`` badge whenever ``is_bot`` is true.

Public surface:
- ``ensure_system_bots()`` — idempotent upsert called once on app start.
- ``post_bot_message(...)``  — send a message from a bot into the
                               recipient's bot DM (room is auto-created).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.socket import sio
from app.db import async_session_factory
from app.models.domain import (
    ChatUserReplica,
    Message,
    Room,
    RoomParticipant,
)


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SystemBot:
    id: int
    username: str
    first_name: str
    last_name: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# Stable IDs > any realistic user.id. user-service autoincrement reaches
# the millions only on huge tenants; bots stay above that ceiling.
BOT_CALENDAR = SystemBot(id=9_000_001, username="bot-calendar", first_name="📅", last_name="Календарь")
BOT_TASKS    = SystemBot(id=9_000_002, username="bot-tasks",    first_name="📋", last_name="Задачи")
BOT_EMAIL    = SystemBot(id=9_000_003, username="bot-email",    first_name="📧", last_name="Почта")
BOT_FILES    = SystemBot(id=9_000_004, username="bot-files",    first_name="📁", last_name="Файлы")
BOT_NEWS     = SystemBot(id=9_000_005, username="bot-news",     first_name="📰", last_name="Новости")
BOT_REQUESTS = SystemBot(id=9_000_006, username="bot-requests", first_name="🧾", last_name="Запросы")

SYSTEM_BOTS: tuple[SystemBot, ...] = (BOT_CALENDAR, BOT_TASKS, BOT_EMAIL, BOT_FILES, BOT_NEWS, BOT_REQUESTS)
BOT_IDS: frozenset[int] = frozenset(b.id for b in SYSTEM_BOTS)


async def ensure_system_bots() -> None:
    """Insert / update the 5 system-bot rows. Idempotent."""
    async with async_session_factory() as session:
        for bot in SYSTEM_BOTS:
            existing = await session.get(ChatUserReplica, bot.id)
            if existing is None:
                session.add(
                    ChatUserReplica(
                        id=bot.id,
                        username=bot.username,
                        first_name=bot.first_name,
                        last_name=bot.last_name,
                        is_active=True,
                        is_bot=True,
                    )
                )
            else:
                # Keep names up-to-date if we ever rename a bot.
                existing.username = bot.username
                existing.first_name = bot.first_name
                existing.last_name = bot.last_name
                existing.is_active = True
                existing.is_bot = True
                session.add(existing)
        await session.commit()
    log.info("system_bots_ensured", count=len(SYSTEM_BOTS))


async def _find_bot_dm(
    session: AsyncSession, user_id: int, bot_id: int
) -> Room | None:
    """Look up the direct chat between a user and a specific bot."""
    rp_user = select(RoomParticipant.room_id).where(RoomParticipant.user_id == user_id)
    rp_bot = select(RoomParticipant.room_id).where(RoomParticipant.user_id == bot_id)
    stmt = (
        select(Room)
        .where(
            Room.room_type == "direct",
            Room.id.in_(rp_user),
            Room.id.in_(rp_bot),
        )
        .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
    )
    return (await session.execute(stmt)).scalars().first()


async def get_or_create_bot_dm(
    session: AsyncSession, *, user_id: int, bot_id: int
) -> Room:
    """Return the user↔bot direct room, creating it on first call."""
    room = await _find_bot_dm(session, user_id, bot_id)
    if room is not None:
        return room

    room = Room(name=None, room_type="direct", is_e2ee=False)
    session.add(room)
    await session.flush()
    session.add(RoomParticipant(room_id=room.id, user_id=user_id, role="member"))
    session.add(RoomParticipant(room_id=room.id, user_id=bot_id, role="admin"))
    await session.commit()

    # Reload with relationships populated so the broadcaster downstream can
    # serialize sender info.
    fresh = await session.execute(
        select(Room)
        .where(Room.id == room.id)
        .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
    )
    return fresh.scalar_one()


async def _emit_bot_message_socket(message: Message, room: Room) -> None:
    """Broadcast a freshly-saved bot message via Socket.IO.

    Same payload shape as ``MessengerService.send_message``, minus the
    attachment block (bots don't attach files for now). Both the room
    channel and each participant's user channel get the message so the
    sidebar updates even if the user hasn't joined the room.
    """
    payload = {
        "room_id": message.room_id,
        "message": {
            "id": str(message.id),
            "room_id": message.room_id,
            "sender_id": message.sender_id,
            "content": message.content,
            "is_encrypted": False,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "attachments": [],
        },
    }
    await sio.emit("message_new", payload, room=f"room:{message.room_id}")
    for participant in room.participants:
        await sio.emit("message_new", payload, room=f"user:{int(participant.user_id)}")


async def post_bot_message(
    *,
    user_id: int,
    bot: SystemBot,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> Message | None:
    """Send a message from ``bot`` into the user↔bot DM.

    The room is created lazily on first delivery. Returns ``None`` if the
    recipient doesn't exist in the chat_user_replicas table (i.e. user
    hasn't been synced yet via Redis pub/sub) — we'd FK-error trying to
    add them to the room.
    """
    async with async_session_factory() as session:
        recipient = await session.get(ChatUserReplica, user_id)
        if recipient is None or recipient.is_bot:
            log.warning("bot_post_unknown_recipient", user_id=user_id, bot=bot.username)
            return None

        room = await get_or_create_bot_dm(session, user_id=user_id, bot_id=bot.id)

        # Match the existing wire format: plain non-encrypted messages store
        # ``{"text": "..."}``  as JSON in ``content``  so the frontend
        # ``decodeMessageText`` parser already handles them.
        import json

        body = json.dumps({"text": text}, ensure_ascii=False)
        msg = Message(
            room_id=room.id,
            sender_id=bot.id,
            content=body,
            is_encrypted=False,
            metadata_json=metadata,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)

    # Re-open a session to load with relationships for the broadcast
    # (participants need to be eagerly loaded for the socket fan-out).
    async with async_session_factory() as session:
        full_room = await session.execute(
            select(Room)
            .where(Room.id == room.id)
            .options(selectinload(Room.participants))
        )
        await _emit_bot_message_socket(msg, full_room.scalar_one())

    log.info(
        "bot_message_posted",
        bot=bot.username,
        recipient_id=user_id,
        room_id=room.id,
        message_id=str(msg.id),
    )
    return msg
