"""Ограничение частоты — сейчас только блокировка входа по логину (D-S7-3).

Что делает. ``AUTH_LOCKOUT_THRESHOLD`` неудач входа по одному логину за
``AUTH_LOCKOUT_SECONDS`` секунд — и вход по этому логину закрыт на столько же
секунд: ``login_locked`` отдаёт, сколько секунд осталось. Блокировка действует
и при верном пароле, иначе перебор просто продолжился бы до попадания.
Порог ``0`` — выключено (так выкатывается: включают после окна выкатки).

Ключ. ``sha256(SECRET_KEY + канонический логин)``: в Redis нет ни логина, ни
его части, а префикс хеша в логе не раскрывает его, но позволяет сопоставить
строки. Канон согласован с поиском ``auth_service._find_user``, но не
идентичен ему: адрес (есть ``@``) — без регистра, как в поиске, и ещё без
пробелов по краям (поиск пробелы не режет — это отличие намеренное: варианты
«a@b» и « a@b » сливаются в один счётчик и не дают обойти блокировку);
имя пользователя — как есть (``Admin`` и ``admin`` — разные пользователи,
поэтому и счётчики разные); до хеша логин режется до 254 символов, чтобы
мусорный ввод не раздувал работу.

Считаются ВСЕ неудачи, включая неизвестные логины: иначе счётчик сам выдавал бы
оракул «такой логин существует».

Отказ хранилища. Кэш платформы — Redis с ``IGNORE_EXCEPTIONS``: недоступный
Redis отдаёт ``None`` вместо ошибки. Тогда блокировка не действует (вход —
первая дверь платформы, и падение кэша не должно её запирать), а
``fallback("htqweb.ratelimit.store_unavailable", expected=False)`` поднимает
алерт.

Задел. ``_incr`` — общий атомарный счётчик фиксированного окна; лимит запросов
на пользователя (D-S7-4, позже) строится на нём же.
"""
from __future__ import annotations

import hashlib
import math
import time

from django.conf import settings
from django.core.cache import cache
from prometheus_client import Counter

from htqweb.fallback import fallback

#: Блокировки входа по причинам: ``locked`` — порог достигнут, ``rejected`` —
#: попытка отклонена под действующей блокировкой. Вне ``collect_all()``, как
#: ``htqweb_fallback_total``.
auth_lockout_total = Counter(
    "htqweb_auth_lockout_total",
    "Блокировки входа после серии неудач (locked) и отклонённые под ними попытки (rejected)",
    ["reason"],
)

_MAX_LOGIN_LEN = 254
_PREFIX = "ratelimit:login:"


def canonical_login(login: str) -> str:
    """Канонический вид логина — так же различает пользователей ``_find_user``."""
    login = login or ""
    if "@" in login:
        login = login.strip().lower()
    return login[:_MAX_LOGIN_LEN]


def login_digest(login: str) -> str:
    raw = f"{settings.SECRET_KEY}\0{canonical_login(login)}".encode()
    return hashlib.sha256(raw).hexdigest()


def digest_prefix(login: str) -> str:
    """Префикс хеша для лога: сопоставляет строки, не раскрывая логин."""
    return login_digest(login)[:12]


def _threshold() -> int:
    return int(getattr(settings, "AUTH_LOCKOUT_THRESHOLD", 0) or 0)


def _seconds() -> int:
    return int(getattr(settings, "AUTH_LOCKOUT_SECONDS", 900) or 900)


def _incr(key: str, timeout: int) -> int | None:
    """Атомарный счётчик фиксированного окна. ``None`` — хранилище не ответило."""
    for _ in range(3):
        added = cache.add(key, 1, timeout)
        if added is None:
            return None
        if added:
            return 1
        try:
            value = cache.incr(key)
        except ValueError:
            # Ключ истёк между add и incr — заводим окно заново.
            continue
        return value
    return None


def _store_unavailable(op: str) -> None:
    fallback("htqweb.ratelimit.store_unavailable", None,
             reason="хранилище счётчиков не ответило — блокировка входа не действует",
             expected=False, op=op)


def login_locked(login: str) -> int | None:
    """Сколько секунд вход по логину закрыт; ``None`` — не заблокирован."""
    if _threshold() <= 0:
        return None
    until = cache.get(f"{_PREFIX}{login_digest(login)}:lock")
    if not until:
        return None
    left = math.ceil(float(until) - time.time())
    if left <= 0:
        return None
    auth_lockout_total.labels(reason="rejected").inc()
    return left


def register_login_failure(login: str) -> None:
    """Записать неудачу; на пороге — закрыть вход на ``AUTH_LOCKOUT_SECONDS``."""
    threshold = _threshold()
    if threshold <= 0:
        return
    base = f"{_PREFIX}{login_digest(login)}"
    seconds = _seconds()
    count = _incr(f"{base}:n", seconds)
    if count is None:
        _store_unavailable("incr")
        return
    if count >= threshold:
        cache.set(f"{base}:lock", time.time() + seconds, seconds)
        cache.delete(f"{base}:n")
        auth_lockout_total.labels(reason="locked").inc()


def reset_login(login: str) -> None:
    """Снять блокировку и обнулить счётчик (успешный вход, смена пароля, ``auth_unlock``)."""
    base = f"{_PREFIX}{login_digest(login)}"
    cache.delete_many([f"{base}:n", f"{base}:lock"])
