"""Присутствие (онлайн / «был в сети») — целиком в Redis, БД не участвует.

Пишет socket.py (ASGI): connect -> ``SADD`` sid в множество подключений
пользователя, disconnect -> ``SREM``; когда множество опустело — пользователь
оффлайн, момент запоминается в ``last_seen``. Несколько вкладок = несколько
sid в множестве, оффлайн наступает только когда закрыта последняя.

Читает HTTP-эндпойнт ``GET /api/messenger/v1/users/presence`` (views.py) —
фронт спрашивает статусы собеседников пачкой.

Redis — ТОТ ЖЕ, что у Django-кэша (``settings.CACHES['default']``, db /8):
и ASGI-, и WSGI-сторона должны видеть одни ключи, а django_redis уже даёт
готовое подключение WSGI-стороне. В тестах кэш — locmem, Redis нет: все
функции тихо деградируют (все оффлайн, записи no-op) — присутствие
вспомогательно и не имеет права ничего ронять.

Ключи:
    messenger:presence:conns:<user_id>  — SET активных sid (TTL 12ч — само-
                                          чинится, если процесс умер, не
                                          успев разослать disconnect'ы)
    messenger:presence:last_seen:<user_id> — ISO-время последнего оффлайна
"""
from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

CONNS_KEY = "messenger:presence:conns:%d"
LAST_SEEN_KEY = "messenger:presence:last_seen:%d"
_CONNS_TTL = 12 * 3600
_LAST_SEEN_TTL = 30 * 24 * 3600


def _conn():
    try:
        from django_redis import get_redis_connection

        return get_redis_connection("default")
    except Exception:  # noqa: BLE001 — locmem-кэш в тестах / Redis лёг
        return None


def connection_opened(user_id: int, sid: str) -> bool:
    """Регистрирует подключение. ``True``, если пользователь при этом перешёл
    из оффлайна в онлайн (первая вкладка) — вызывающему стоит разослать
    ``user_online``."""
    conn = _conn()
    if conn is None:
        return False
    try:
        key = CONNS_KEY % user_id
        was_online = conn.scard(key) > 0
        pipe = conn.pipeline()
        pipe.sadd(key, sid)
        pipe.expire(key, _CONNS_TTL)
        pipe.execute()
        return not was_online
    except Exception as exc:  # noqa: BLE001
        logger.warning("presence: connection_opened(%s) не записан: %s", user_id, exc)
        return False


def connection_closed(user_id: int, sid: str) -> bool:
    """Снимает подключение. ``True``, если это была последняя вкладка —
    пользователь ушёл в оффлайн, ``last_seen`` зафиксирован."""
    conn = _conn()
    if conn is None:
        return False
    try:
        key = CONNS_KEY % user_id
        pipe = conn.pipeline()
        pipe.srem(key, sid)
        pipe.scard(key)
        _, remaining = pipe.execute()
        if remaining == 0:
            conn.set(LAST_SEEN_KEY % user_id,
                     datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     ex=_LAST_SEEN_TTL)
            return True
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("presence: connection_closed(%s) не записан: %s", user_id, exc)
        return False


def get_presence(user_ids: list[int]) -> dict[int, dict]:
    """``{user_id: {"online": bool, "last_seen": iso|None}}`` пачкой —
    один pipeline на весь запрос."""
    ids = [int(u) for u in user_ids]
    if not ids:
        return {}
    conn = _conn()
    if conn is None:
        return {uid: {"online": False, "last_seen": None} for uid in ids}
    try:
        pipe = conn.pipeline()
        for uid in ids:
            pipe.scard(CONNS_KEY % uid)
            pipe.get(LAST_SEEN_KEY % uid)
        flat = pipe.execute()
        out: dict[int, dict] = {}
        for i, uid in enumerate(ids):
            raw_seen = flat[i * 2 + 1]
            out[uid] = {
                "online": (flat[i * 2] or 0) > 0,
                "last_seen": raw_seen.decode() if isinstance(raw_seen, bytes) else raw_seen,
            }
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("presence: get_presence не прочитан: %s", exc)
        return {uid: {"online": False, "last_seen": None} for uid in ids}
