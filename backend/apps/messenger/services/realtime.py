"""Рассылка Socket.IO-событий из WSGI-процесса (gunicorn/runserver).

Закрывает «открытый вопрос» порта socket.py (см. его докстринг): исходный
FastAPI-сервис из REST-хендлеров сам звал ``sio.emit(...)``, а при переносе
перенесли только Socket.IO-слой — REST-триггернутая рассылка осталась
несделанной. Итог был виден любому пользователю: фронт слушает
``message_new``/``message_read`` (useMessengerSocket.ts), но сервер их не
шлёт НИКОГДА, и новые сообщения доезжали только 30-секундным поллингом.

Как это работает. Socket.IO-сервер живёт в ДРУГОМ процессе (backend-asgi);
эмитить из WSGI напрямую нечем. python-socketio предусматривает ровно этот
случай: ``socketio.RedisManager(url, write_only=True)`` — клиент, который
публикует событие в тот же Redis-канал (дефолтный ``socketio``), откуда его
подхватывает ``AsyncRedisManager`` ASGI-процесса и раздаёт по комнатам.
URL и условие выбора Redis — буквально те же, что в ``socket.py::
_redis_url_for_socketio`` (CELERY_BROKER_URL, ``redis://``-схема): если
менеджеры смотрят в разные Redis/каналы, события молча пропадают.

Все функции неубиваемые: рассылка — best-effort поверх уже совершённой
записи в БД; недоступный Redis деградирует до старого поведения (поллинг),
но не роняет HTTP-запрос. В тестах (``CELERY_BROKER_URL = "memory://"``)
эмиттер отключён и всё превращается в no-op — Socket.IO там не поднимается.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from django.conf import settings

logger = logging.getLogger(__name__)

_UNSET = object()
_manager: Any = _UNSET  # лениво: socketio.RedisManager | None


def _redis_url() -> str | None:
    """Копия условия ``socket.py::_redis_url_for_socketio`` — ОБЯЗАНА
    оставаться синхронной с ней (оба менеджера должны смотреть в один
    Redis, иначе события уходят в пустоту)."""
    url = getattr(settings, "CELERY_BROKER_URL", None) or getattr(settings, "REDIS_URL", None)
    if isinstance(url, str) and url.startswith(("redis://", "rediss://")):
        return url
    return None


def _get_manager():
    global _manager
    if _manager is _UNSET:
        url = _redis_url()
        if url is None:
            _manager = None
        else:
            try:
                import socketio

                _manager = socketio.RedisManager(url, write_only=True)
            except Exception as exc:  # noqa: BLE001 — деградируем до поллинга
                logger.warning("realtime: RedisManager недоступен (%s), события отключены", exc)
                _manager = None
    return _manager


def _emit(event: str, data: dict, *, room: str) -> None:
    mgr = _get_manager()
    if mgr is None:
        return
    try:
        mgr.emit(event, data, room=room)
    except Exception as exc:  # noqa: BLE001 — best-effort поверх записанной БД
        logger.warning("realtime: emit %s в %s не удался: %s", event, room, exc)


# ── доменные события (имена — контракт useMessengerSocket.ts, не менять) ──

def message_new(room_id: int, message: dict, participant_ids: Iterable[int] = ()) -> None:
    """Новое сообщение: в канал комнаты (открытые чаты) и в персональные
    каналы участников (бейджи непрочитанного/уведомления у тех, кто в
    ДРУГОЙ комнате или вообще не на странице мессенджера) — как исходник,
    рассылавший в комнату и в персональные каналы разом. Дубль на клиенте
    безопасен: обработчик идемпотентен (инвалидация react-query кэша)."""
    payload = {"room_id": room_id, "message": message}
    _emit("message_new", payload, room=f"room:{room_id}")
    for uid in participant_ids:
        _emit("message_new", payload, room=f"user:{uid}")


def message_read(room_id: int, message_id, reader_user_id: int) -> None:
    _emit("message_read",
          {"room_id": room_id, "message_id": str(message_id), "reader_user_id": reader_user_id},
          room=f"room:{room_id}")


def message_edited(room_id: int, message: dict) -> None:
    _emit("message_edited", {"room_id": room_id, "message": message}, room=f"room:{room_id}")


def message_deleted(room_id: int, message_id) -> None:
    _emit("message_deleted", {"room_id": room_id, "message_id": str(message_id)},
          room=f"room:{room_id}")


def room_updated(room_id: int, participant_ids: Iterable[int]) -> None:
    """Состав/атрибуты комнаты изменились (добавили участника, сменили роль,
    переименовали). Шлётся в ПЕРСОНАЛЬНЫЕ каналы: только что добавленный
    участник ещё не подписан на ``room:{id}`` (авто-подписка происходит при
    connect), поэтому канал комнаты его бы не достал — а персональный канал
    есть у каждого подключённого. Фронт в ответ перезапрашивает список
    комнат и делает ``join_room``."""
    for uid in participant_ids:
        _emit("room_updated", {"room_id": room_id}, room=f"user:{uid}")
