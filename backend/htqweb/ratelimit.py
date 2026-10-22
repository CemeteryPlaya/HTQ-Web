"""Ограничение частоты: блокировка входа по логину (D-S7-3) и общий лимитер
запросов ``hit`` (тендерный портал, T3.1).

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

Общий лимитер. ``hit(bucket, key, limit=, window=)`` — не больше ``limit``
обращений в окне ``window`` секунд; окно фиксированное и выровнено по часам
(номер окна ``time // window`` — часть ключа), поэтому ``retry_after`` знает
конец окна без чтения TTL. Ключ — ``ratelimit:<bucket>:<sha256(key)[:32]>``:
сырое значение (токен ссылки, адрес) в хранилище не попадает. Недоступное
хранилище — пропуск с ``fallback(expected=False)`` (лимит — защита от шума,
а не замок); ``fail_closed=True`` — отказ (OTP, этап 4: там перебор кода и есть
атака). На том же ``_incr`` построится лимит запросов на пользователя (D-S7-4).
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

_series_ready = False


def _ensure_series() -> None:
    """Обе серии счётчика — с нуля при первом обращении включённой блокировки:
    без этого первая блокировка после старта процесса не видна ``increase()``
    правила ``htqweb-auth-lockout-burst`` (как ``_init_verdict_labels`` антивируса)."""
    global _series_ready
    if not _series_ready:
        for reason in ("locked", "rejected"):
            auth_lockout_total.labels(reason=reason)
        _series_ready = True


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


def _store_unavailable(op: str, *,
                       reason: str = "хранилище счётчиков не ответило — блокировка "
                                     "входа не действует") -> None:
    fallback("htqweb.ratelimit.store_unavailable", None, reason=reason,
             expected=False, op=op)


_HIT_PREFIX = "ratelimit:"


def _slot(window: int) -> int:
    return int(time.time() // window)


def _hit_key(bucket: str, key: str, window: int) -> str:
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:32]
    return f"{_HIT_PREFIX}{bucket}:{digest}:{window}:{_slot(window)}"


def hit(bucket: str, key: str, *, limit: int, window: int, fail_closed: bool = False) -> bool:
    """Засчитать обращение: ``True`` — в пределах ``limit`` за окно ``window``
    секунд, ``False`` — сверх лимита (ответ 429 с ``retry_after``)."""
    if limit < 1 or window < 1:
        raise ValueError("limit и window — положительные целые")
    count = _incr(_hit_key(bucket, key, window), window)
    if count is None:
        if fail_closed:
            return False
        _store_unavailable(f"hit:{bucket}",
                           reason="хранилище счётчиков не ответило — лимит запросов "
                                  "не действует")
        return True
    return count <= limit


def retry_after(bucket: str, key: str, window: int) -> int:
    """Секунд до конца текущего окна (для ``Retry-After``), не меньше 1.
    ``bucket``/``key`` — для симметрии с ``hit``: окно у всех ключей общее."""
    left = window - (time.time() % window)
    return max(1, math.ceil(left))


def login_locked(login: str) -> int | None:
    """Сколько секунд вход по логину закрыт; ``None`` — не заблокирован."""
    if _threshold() <= 0:
        return None
    _ensure_series()
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
    _ensure_series()
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
