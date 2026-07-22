"""Публичный API аппки messenger для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза messenger, PLAN.md §6.5 — workers/admin,
последняя под-задача домена). Потребитель: ``apps.approvals`` (диспатч
уведомлений из workflow-движка, Поток B). Прямой импорт ``apps.messenger.*``
из другой аппки запрещён (``apps/core/tests/test_app_isolation.py``) — только
через этот модуль. Сигнатуры зафиксированы совместно с Потоком B (PLAN.md §7)
и не меняются в одностороннем порядке.

Обе функции синхронные (обычные аппки этого монолита — синхронный Django
ORM), а рассылка идёт через ``apps.messenger.socket.sio``, чей ``emit`` —
корутина -> оборачивается ``asgiref.sync.async_to_sync`` (тот же приём, что
``apps/messenger/services/system_bots_service.py``). ``AsyncRedisManager``
(когда сконфигурирован реальный Redis, см. ``socket.py::
_redis_url_for_socketio``) доставляет событие во ВСЕ процессы messenger, не
только в текущий — обычный сценарий межаппного вызова из другого процесса
Celery/Django здесь не отличается от вызова из HTTP-вьюхи того же процесса.

Ни ``dispatch_notification``, ни ``send_system_message`` не являются
буквальным портом какого-то конкретного эндпойнта/воркера FastAPI-исходника
— это НОВЫЙ кросс-доменный контракт этого Django-монолита (PLAN.md §7,
таблица interface): в микросервисной архитектуре тот же манёвр делали Redis
pub/sub-подписчики (``app/workers/bot_dispatch.py`` — рендерит ``notify.*``
события в текстовые DM от системных ботов; ``app/services/
notify_publish.py`` — паблишит ``notify.new_chat_message`` для task-service).
Оба этих механизма — Р2, НЕ портируются целиком (см. ``apps/messenger/
socket.py`` и ``apps/messenger/services/messenger_service.py`` докстринги):
у ``bot_dispatch.py`` не осталось издателей событий (публиковавшие их
FastAPI-сервисы либо ещё не портированы, либо в этом монолите заменяют
Redis pub/sub прямым вызовом interface — см. PLAN.md §3), а
``notify_publish.py``'s единственный потребитель (task-service) вне периметра
Потока A. Вместо копирования той обвязки, эти две функции реализуют РОВНО тот
наблюдаемый эффект, который контракт PLAN.md §7 требует от messenger как
соседа: доставить произвольное уведомление набору пользователей
(``dispatch_notification``) и добавить системное сообщение в существующую
комнату (``send_system_message``) — оба через тот же самый Socket.IO-слой,
которым живой messenger и так рассылает ``message_new``/``message_read``.
"""
from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync

from apps.core.services import require_service

logger = logging.getLogger(__name__)


def dispatch_notification(user_ids: list[int], payload: dict) -> None:
    """Разослать произвольное уведомление указанным пользователям.

    Фан-аут ЧЕРЕЗ Socket.IO — событие ``"notification"`` в персональный канал
    (``user:<id>``) каждого получателя, ``payload`` передаётся КАК ЕСТЬ (без
    какой-либо интерпретации/шаблонизации — messenger здесь чистый курьер,
    смысл ``payload`` целиком на совести вызывающего домена). Никакой
    персистентности на стороне messenger: здесь нет модели ``Notification``
    (та жила в task-service исходника, вне периметра Потока A, см.
    ``services/notify_publish.py`` докстринг) — доставка best-effort/
    at-most-once, тот же контракт, что уже несёт остальной Socket.IO-слой
    (``apps/messenger/socket.py``: пропущенное событие для не-подключённого
    клиента не буферизуется).

    Пустой ``user_ids`` — no-op (``sio.emit`` не вызывается вовсе).
    """
    require_service("messenger")

    if not user_ids:
        return

    from apps.messenger.socket import sio

    rooms = [f"user:{int(uid)}" for uid in user_ids]
    async_to_sync(sio.emit)("notification", payload, room=rooms)


def send_system_message(room_id: int, text: str) -> None:
    """Создать системное сообщение в существующей комнате и разослать его.

    Р2 (см. ``apps/messenger/models.py::Message`` докстринг): у ``Message``
    нет отдельной колонки "type" (фронтовый ``msg_type: 'system'`` — мёртвое,
    никогда не заполняемое поле даже в самом FastAPI-исходнике — ни бэкенд,
    ни фронт его не пишут никуда, только объявляют в TS-типе). Системность
    сообщения здесь выражена ДВУМЯ существующими полями, без новой миграции:
    ``sender_id=None`` (никакого человека-отправителя) + ``metadata_json=
    {"system": True}`` (явный маркер для будущего потребителя, который
    захочет визуально отличить системные сообщения). ``content`` кодируется
    тем же JSON-конвертом ``{"text": ...}``, которым фронт (``MessengerPage.
    tsx``) и без того оборачивает ЛЮБОЕ текстовое сообщение — ``
    decodeMessageText`` на фронте уже умеет это парсить, отдельного релиза не
    требуется.

    Best-effort по контракту PLAN.md (§3: «недоступность hr/messenger не
    роняет workflow вызывающего Потока B») — несуществующий ``room_id``
    логируется и молча игнорируется (``None`` — единственный тип возврата
    контракта, исключений на «плохой» room_id не бросается), а не поднимает
    исключение, которое обрушило бы вызывающий workflow.
    """
    require_service("messenger")

    from apps.messenger.models import Message, Room

    room = Room.objects.filter(id=room_id).prefetch_related("participants").first()
    if room is None:
        logger.warning("send_system_message_room_not_found room_id=%s", room_id)
        return

    body = json.dumps({"text": text}, ensure_ascii=False)
    msg = Message.objects.create(
        room=room, sender_id=None, content=body, is_encrypted=False,
        metadata_json={"system": True},
    )

    from apps.messenger.socket import sio

    emit = async_to_sync(sio.emit)
    event_payload = {
        "room_id": msg.room_id,
        "message": {
            "id": str(msg.id),
            "room_id": msg.room_id,
            "sender_id": None,
            "content": msg.content,
            "is_encrypted": False,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "attachments": [],
        },
    }
    emit("message_new", event_payload, room=f"room:{room_id}")
    for participant in room.participants.all():
        emit("message_new", event_payload, room=f"user:{int(participant.user_id)}")
