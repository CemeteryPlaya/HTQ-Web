"""Системные боты (Календарь/Задачи/Почта/Файлы/Новости/Запросы) — порт
``services/messenger/app/services/system_bots.py`` (workers/admin
под-задача, PLAN.md §6.5, последняя под-задача messenger).

Р2 (см. ``apps/messenger/models.py`` докстринг файла): исходник хранил боты
как строки в ``chat_user_replicas`` (реального FK ``RoomParticipant.user_id``/
``Message.sender_id`` -> ``chat_user_replicas.id``, требующего, чтобы строка
бота существовала ДО первого сообщения — отсюда ``ensure_system_bots()``,
вызывавшийся один раз при старте приложения). Эта таблица здесь НЕ
портируется; ``RoomParticipant.user_id``/``Message.sender_id`` в этом порту —
голые ``IntegerField`` БЕЗ FK — им не нужна предварительно существующая
строка ни в какой таблице, чтобы принять числовой id бота. Поэтому
``ensure_system_bots()`` здесь СТАНОВИТСЯ ИЗЛИШНИМ и намеренно не портируется:
нет целевой таблицы, которую нужно было бы упреждающе заполнить.

ID ботов — те же стабильные константы, что в исходнике (``9_000_001+`` —
выше любого реалистичного ``user-service``-id, коллизия с реальным
пользователем невозможна).

``post_bot_message`` проверяет, что получатель — известный, живой,
НЕ-бот пользователь, через ``apps.users.interface.get_user_brief`` (единственная
разрешённая дверь к чужим данным, apps/core/tests/test_app_isolation.py).
Исходник дополнительно проверял ``recipient.is_bot`` в реплике — здесь эта
проверка избыточна другим путём: ID ботов (9_000_001+) заведомо никогда не
существуют как строки ``apps.users.User`` (это реальная, отдельная от ботов
таблица), поэтому ``get_user_brief(bot_id)`` естественно вернёт ``None`` для
любого бота, и «получатель — другой бот» отсекается тем же самым guard'ом
(«получатель неизвестен»), без отдельной проверки ``is_bot``.

Socket.IO-вещание (``_emit_bot_message_socket`` исходника) — синхронная
обёртка (``asgiref.sync.async_to_sync``) над ``apps.messenger.socket.sio``,
буквальный порт: событие ``message_new`` в канал комнаты и в персональный
канал каждого участника (тот же двойной fan-out, что и в исходнике — чтобы
сайдбар обновлялся, даже если получатель не открыл конкретный чат).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync

from apps.messenger.models import Message, Room, RoomParticipant
from apps.users import interface as users_interface

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemBot:
    id: int
    username: str
    first_name: str
    last_name: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# Стабильные id > любой реалистичный user.id — буквальный порт исходника.
BOT_CALENDAR = SystemBot(id=9_000_001, username="bot-calendar", first_name="\U0001F4C5", last_name="Календарь")
BOT_TASKS = SystemBot(id=9_000_002, username="bot-tasks", first_name="\U0001F4CB", last_name="Задачи")
BOT_EMAIL = SystemBot(id=9_000_003, username="bot-email", first_name="\U0001F4E7", last_name="Почта")
BOT_FILES = SystemBot(id=9_000_004, username="bot-files", first_name="\U0001F4C1", last_name="Файлы")
BOT_NEWS = SystemBot(id=9_000_005, username="bot-news", first_name="\U0001F4F0", last_name="Новости")
BOT_REQUESTS = SystemBot(id=9_000_006, username="bot-requests", first_name="\U0001F9FE", last_name="Запросы")

SYSTEM_BOTS: tuple[SystemBot, ...] = (
    BOT_CALENDAR, BOT_TASKS, BOT_EMAIL, BOT_FILES, BOT_NEWS, BOT_REQUESTS,
)
BOT_IDS: frozenset[int] = frozenset(b.id for b in SYSTEM_BOTS)
BOTS_BY_USERNAME: dict[str, SystemBot] = {b.username: b for b in SYSTEM_BOTS}


def _find_bot_dm(user_id: int, bot_id: int) -> Room | None:
    """Порт ``_find_bot_dm``: личный чат между пользователем и конкретным ботом."""
    rp_user = RoomParticipant.objects.filter(user_id=user_id).values("room_id")
    rp_bot = RoomParticipant.objects.filter(user_id=bot_id).values("room_id")
    return (
        Room.objects.filter(room_type="direct")
        .filter(id__in=rp_user)
        .filter(id__in=rp_bot)
        .prefetch_related("participants")
        .first()
    )


def get_or_create_bot_dm(*, user_id: int, bot_id: int) -> Room:
    """Порт ``get_or_create_bot_dm``: личный чат пользователь<->бот, создаётся
    при первом обращении."""
    room = _find_bot_dm(user_id, bot_id)
    if room is not None:
        return room

    room = Room.objects.create(name=None, room_type="direct", is_e2ee=False)
    RoomParticipant.objects.create(room=room, user_id=user_id, role="member")
    RoomParticipant.objects.create(room=room, user_id=bot_id, role="admin")
    return room


def _emit_bot_message_socket(message: Message, room: Room) -> None:
    """Порт ``_emit_bot_message_socket`` — рассылка в канал комнаты и в
    персональный канал каждого участника."""
    from apps.messenger.socket import sio

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
    emit = async_to_sync(sio.emit)
    emit("message_new", payload, room=f"room:{message.room_id}")
    for participant in room.participants.all():
        emit("message_new", payload, room=f"user:{int(participant.user_id)}")


def post_bot_message(
    *, user_id: int, bot: SystemBot, text: str, metadata: dict[str, Any] | None = None,
) -> Message | None:
    """Порт ``post_bot_message``: отправляет сообщение от ``bot`` в личный
    чат пользователь<->бот (создаётся лениво при первой доставке).

    ``None``, если получатель не резолвится в живого пользователя через
    ``apps.users.interface.get_user_brief`` (неизвестный/удалённый
    пользователь ИЛИ сам id бота — см. докстринг модуля)."""
    recipient = users_interface.get_user_brief(user_id)
    if recipient is None:
        logger.warning("bot_post_unknown_recipient user_id=%s bot=%s", user_id, bot.username)
        return None

    room = get_or_create_bot_dm(user_id=user_id, bot_id=bot.id)

    # Тот же wire-формат, что и обычные/остальные сообщения фронта
    # (``JSON.stringify({text})`` в MessengerPage.tsx) — decodeMessageText
    # парсит JSON независимо от отправителя.
    body = json.dumps({"text": text}, ensure_ascii=False)
    msg = Message.objects.create(
        room=room, sender_id=bot.id, content=body, is_encrypted=False, metadata_json=metadata,
    )

    fresh_room = Room.objects.filter(id=room.id).prefetch_related("participants").first()
    _emit_bot_message_socket(msg, fresh_room)

    logger.info(
        "bot_message_posted bot=%s recipient_id=%s room_id=%s message_id=%s",
        bot.username, user_id, room.id, msg.id,
    )
    return msg
