"""Socket.IO — messenger real-time transport (Поток A, фаза 8, PLAN.md §6.5).

Порт ``services/messenger/app/api/socket.py`` (+ ``app/main.py`` — как
``sio_app`` монтировался в FastAPI-приложении). Смонтировано в Django поверх
WSGI в ``htqweb/asgi.py`` (якорь ``messenger:socketio``, ТОЛЬКО эта секция).

Event-протокол — БЕЗ изменений (фронтовый socket.io-client, ``frontend/src/
features/messenger/hooks/useMessengerSocket.ts``, не трогаем):

  Server → Client:
    - message_new     {room_id, message}
    - message_read    {room_id, message_id, reader_user_id}
    - user_typing     {room_id, user_id, is_typing}
    - message_edited  {room_id, message}          (REST-триггер, realtime.py)
    - message_deleted {room_id, message_id}       (REST-триггер, realtime.py)
    - room_updated    {room_id}                   (REST-триггер, realtime.py)
    - user_online     {user_id}                   (presence, connect)
    - user_offline    {user_id, last_seen}        (presence, disconnect)

  Client → Server:
    - join_room   {room_id}
    - leave_room  {room_id}
    - typing      {room_id, is_typing}
    - mark_read   {room_id, message_id}

Исходник несёт РОВНО 6 ``@sio.event`` хендлеров (``connect``, ``disconnect``,
``join_room``, ``leave_room``, ``typing``, ``mark_read``) — никакого
отдельного ``message``-события нет (отправка сообщения — REST-only, ``POST
/messages/``); порт переносит все 6, буквально.

Р2 (см. бриф п.5, ``apps/messenger/services/messenger_service.py`` докстринг
у ``send_message``/``mark_read``): исходный ``app/services/notify_publish.py``
(Redis pub/sub -> ``CHANNEL_NEW_CHAT_MESSAGE``, потребитель — task-service) НЕ
портируется — вне периметра Поток A (нет task-service в этом монолите).
Socket.IO продолжает рассылать сам через ``sio.emit``/``AsyncRedisManager`` —
этот механизм ортогонален notify_publish и переносится целиком.

REST-триггернутая рассылка (в исходнике REST-хендлеры сами звали
``sio.emit``) при порте осталась несделанной («открытый вопрос» той
под-задачи) — ЗАКРЫТО 2026-07-28: WSGI-процесс публикует события через
``services/realtime.py`` (``socketio.RedisManager(write_only=True)`` в тот же
Redis-канал, что и ``AsyncRedisManager`` ниже), см. вызовы в
``messenger_service.send_message/mark_read/edit_message/delete_message`` и
``membership_service``. До этого фронт слушал ``message_new``, которого
сервер не слал никогда, и жил на 30-секундном поллинге.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

import socketio
from asgiref.sync import sync_to_async
from django.conf import settings
from pydantic import ValidationError

from apps.core.services import ServiceDisabled, require_service
from apps.messenger.models import RoomParticipant
from apps.messenger.services import presence
from htqweb.authn.jwt import AuthError, decode_token

logger = logging.getLogger(__name__)


def _redis_url_for_socketio() -> str | None:
    """Redis URL for ``AsyncRedisManager``, or ``None`` to fall back to
    python-socketio's default in-process manager.

    Дев/прод: ``CELERY_BROKER_URL``/``REDIS_URL`` (``htqweb/settings/base.py``)
    указывают на реальный Redis (``redis://...``) -> ``AsyncRedisManager``, как
    исходник (``socketio.AsyncRedisManager(settings.redis_url)``), чтобы
    несколько реплик messenger могли раздавать события в одни и те же rooms.

    Тесты (``htqweb/settings/test.py``): ``CELERY_BROKER_URL = "memory://"`` —
    НЕ ``redis://`` URL, Redis в тестовом окружении не гарантирован ->
    дефолтный in-memory менеджер (конструирование ``AsyncRedisManager`` не
    должно падать при импорте модуля в тестах, см. бриф п.1)."""
    url = getattr(settings, "CELERY_BROKER_URL", None) or getattr(settings, "REDIS_URL", None)
    if isinstance(url, str) and url.startswith(("redis://", "rediss://")):
        return url
    return None


_redis_url = _redis_url_for_socketio()

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    client_manager=socketio.AsyncRedisManager(_redis_url) if _redis_url else None,
)


def _extract_token(auth: dict[str, Any] | None, environ: dict[str, Any]) -> str | None:
    """Порт ``_extract_token``: JWT из ``auth`` dict, query string, или
    заголовка Authorization — в этом порядке, буквально."""
    if auth and isinstance(auth, dict):
        token = auth.get("token") or auth.get("jwt")
        if token:
            return str(token)

    qs = environ.get("QUERY_STRING") or ""
    if qs:
        params = parse_qs(qs)
        for key in ("token", "jwt", "access_token"):
            if params.get(key):
                return params[key][0]

    auth_header = environ.get("HTTP_AUTHORIZATION") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip() or None
    return None


def _decode_jwt_or_none(token: str):
    """Декод/валидация через ``htqweb.authn.jwt.decode_token`` (эталон
    брифа) — ``None`` при невалидном/недекодируемом токене.

    Исходник различает ``token_expired``/``invalid_token`` (два разных
    ``jwt`` exceptions); ``decode_token`` заворачивает все ``PyJWTError`` в
    один ``AuthError`` — та же двойная защита (``AuthError``,
    ``ValidationError``), что ``htqweb/http.py::_authenticate_jwt`` (``
    ValidationError`` — если в payload нет обязательного ``user_id``).
    Огрубление причины отказа (нет отдельного "token_expired") — сознательный
    компромисс порта на общий эталон декодера, не "странность исходника"."""
    try:
        return decode_token(token)
    except (AuthError, ValidationError):
        return None


def _user_room_ids_sync(user_id: int) -> list[int]:
    """Порт ``_user_room_ids``: все комнаты, где пользователь — участник."""
    return list(RoomParticipant.objects.filter(user_id=user_id).values_list("room_id", flat=True))


def _user_is_in_room_sync(user_id: int, room_id: int) -> bool:
    """Порт ``_user_is_in_room``."""
    return RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).exists()


def _persist_last_read_sync(room_id: int, user_id: int, message_id) -> bool:
    """Порт тела ``async with async_session_factory() as db: ...`` внутри
    WS-хендлера ``mark_read``. Возвращает ``False`` (no-op), если вызывающий
    не участник комнаты — как исходник (``if not rp: return``)."""
    rp = RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).first()
    if rp is None:
        return False
    rp.last_read_message_id = message_id
    rp.save(update_fields=["last_read_message_id", "updated_at"])
    return True


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None):
    """Порт ``connect``. Р10 (бриф п.2): ``ServiceGateMiddleware`` не
    покрывает WS-scope (``PREFIX_TO_SERVICE`` явно пропускает ``/ws/*``,
    см. ``htqweb/middleware/service_gate.py``) -> ПЕРВЫМ делом гейтим сами,
    ДО извлечения/валидации токена (буквальный порядок брифа)."""
    try:
        await sync_to_async(require_service)("messenger")
    except ServiceDisabled as exc:
        logger.warning("socket_connect_rejected sid=%s reason=service_disabled", sid)
        raise socketio.exceptions.ConnectionRefusedError(exc.message or "service_disabled") from exc

    token = _extract_token(auth, environ)
    if not token:
        logger.warning("socket_connect_rejected sid=%s reason=missing_token", sid)
        raise socketio.exceptions.ConnectionRefusedError("missing_token")

    payload = _decode_jwt_or_none(token)
    if payload is None:
        logger.warning("socket_connect_rejected sid=%s reason=invalid_token", sid)
        raise socketio.exceptions.ConnectionRefusedError("invalid_token")

    user_id = payload.user_id
    if not user_id:
        logger.warning("socket_connect_rejected sid=%s reason=no_user_id_claim", sid)
        raise socketio.exceptions.ConnectionRefusedError("no_user_id_claim")

    await sio.save_session(
        sid,
        {
            "user_id": int(user_id),
            "username": payload.username or "",
            "is_admin": bool(payload.is_admin),
        },
    )

    # Auto-subscribe the socket to every room the user belongs to (порт
    # комментария исходника: без этого message_new доходит только до
    # активно открытого чата — sidebar/unread остаются протухшими).
    room_ids: list[int] = []
    try:
        room_ids = await sync_to_async(_user_room_ids_sync)(int(user_id))
        for rid in room_ids:
            await sio.enter_room(sid, f"room:{rid}")
        # Персональный канал — события не привязанные к конкретной комнате
        # (напр. новый чат создаётся).
        await sio.enter_room(sid, f"user:{int(user_id)}")
        logger.info("socket_auto_joined sid=%s user_id=%s rooms=%d", sid, user_id, len(room_ids))
    except Exception:  # noqa: BLE001 — никогда не блокируем connect на сбое join
        logger.exception("socket_auto_join_failed sid=%s user_id=%s", sid, user_id)

    # Присутствие: sid регистрируется в Redis (services/presence.py); при
    # переходе оффлайн->онлайн (первая вкладка) — user_online в комнаты
    # пользователя, чтобы зелёные точки у собеседников зажглись сразу.
    try:
        became_online = await sync_to_async(presence.connection_opened)(int(user_id), sid)
        if became_online:
            for rid in room_ids:
                await sio.emit(
                    "user_online", {"user_id": int(user_id)},
                    room=f"room:{rid}", skip_sid=sid,
                )
    except Exception:  # noqa: BLE001 — присутствие не имеет права ломать connect
        logger.exception("presence_track_failed sid=%s user_id=%s", sid, user_id)

    logger.info("socket_connected sid=%s user_id=%s", sid, user_id)


@sio.event
async def disconnect(sid: str):
    """Порт ``disconnect`` + учёт присутствия: когда закрылась ПОСЛЕДНЯЯ
    вкладка пользователя — user_offline (с ``last_seen``) в его комнаты."""
    try:
        session = await sio.get_session(sid)
    except KeyError:
        session = {}
    user_id = session.get("user_id")
    if user_id is not None:
        try:
            went_offline = await sync_to_async(presence.connection_closed)(int(user_id), sid)
            if went_offline:
                import datetime as _dt

                last_seen = _dt.datetime.now(_dt.timezone.utc).isoformat()
                for rid in await sync_to_async(_user_room_ids_sync)(int(user_id)):
                    await sio.emit(
                        "user_offline",
                        {"user_id": int(user_id), "last_seen": last_seen},
                        room=f"room:{rid}",
                    )
        except Exception:  # noqa: BLE001
            logger.exception("presence_untrack_failed sid=%s user_id=%s", sid, user_id)
    logger.info("socket_disconnected sid=%s user_id=%s", sid, user_id)


@sio.event
async def join_room(sid: str, data: dict[str, Any]):
    """Порт ``join_room``: подписка на комнату — только если вызывающий её
    участник."""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return {"ok": False, "error": "missing_room_id"}

    try:
        room_id_int = int(room_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_room_id"}

    if not await sync_to_async(_user_is_in_room_sync)(user_id, room_id_int):
        logger.warning("join_room_denied user_id=%s room_id=%s", user_id, room_id_int)
        return {"ok": False, "error": "not_a_member"}

    await sio.enter_room(sid, f"room:{room_id_int}")
    logger.info("join_room user_id=%s room_id=%s", user_id, room_id_int)
    return {"ok": True}


@sio.event
async def leave_room(sid: str, data: dict[str, Any]):
    """Порт ``leave_room``."""
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return {"ok": False, "error": "missing_room_id"}
    try:
        await sio.leave_room(sid, f"room:{int(room_id)}")
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_room_id"}
    return {"ok": True}


@sio.event
async def typing(sid: str, data: dict[str, Any]):
    """Порт ``typing``: форвардит typing-индикатор остальным участникам
    комнаты (``skip_sid`` — не себе)."""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return
    is_typing = bool(data.get("is_typing", True)) if isinstance(data, dict) else True
    await sio.emit(
        "user_typing",
        {"room_id": int(room_id), "user_id": user_id, "is_typing": is_typing},
        room=f"room:{int(room_id)}",
        skip_sid=sid,
    )


@sio.event
async def mark_read(sid: str, data: dict[str, Any]):
    """Порт ``mark_read`` (WS-сторона: пишет ``last_read_message_id`` и
    рассылает ``message_read``; зеркалит ``POST /messages/room/{room_id}/
    read/{message_id}`` — но REST-сторона это событие сама НЕ шлёт, см.
    докстринг модуля)."""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    if not isinstance(data, dict):
        return
    room_id = data.get("room_id")
    message_id = data.get("message_id")
    if room_id is None or not message_id:
        return

    updated = await sync_to_async(_persist_last_read_sync)(int(room_id), user_id, message_id)
    if not updated:
        return

    await sio.emit(
        "message_read",
        {"room_id": int(room_id), "message_id": str(message_id), "reader_user_id": user_id},
        room=f"room:{int(room_id)}",
        skip_sid=sid,
    )
