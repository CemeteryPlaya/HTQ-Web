"""Админ-панель инфраструктуры — порт ``services/admin/app/api/v1/
infrastructure.py`` (539 строк) снесённого при cutover'е admin-сервиса.

Зачем понадобился порт: страница ``frontend/src/pages/AdminInfrastructure.tsx``
осталась в роутере (``/admin/infrastructure``) и в сайдбаре админа, а весь её
API (``/api/admin/v1/infrastructure/*``, 6 эндпойнтов) уехал вместе с
admin-сервисом — любой заход админа давал шесть 404-ок. Формы ответов
воспроизведены 1:1 по типам из той страницы, менять фронт не потребовалось.

Живёт в ``apps.core``, а не в отдельной аппке: это платформенная, а не
доменная функция (соседний житель того же модуля — реестр вкл/выкл сервисов
``/api/core/v1/services/``), у неё нет собственных моделей, и заводить ради
неё новую аппку значило бы плодить пустой пакет с миграциями.

Отличия от источника — все вынужденные, каждое объяснено на месте:

1. **Ресурс ``mongo`` убран.** MongoDB снесена вместе с поколением FastAPI
   (хранила HR-документы и старую админку) — показывать карточку и
   health-check несуществующего сервиса нечестно. Осталось три ресурса:
   postgres, redis, minio.
2. **Повторная аутентификация — в процессе, без HTTP.** Источник ходил
   ``POST http://user-service/api/users/v1/token/`` по сети; здесь сосед
   рядом, зовём ``apps.users.interface.verify_password`` (межаппный контакт
   ТОЛЬКО через interface — apps/core/tests/test_app_isolation.py).
3. **async -> sync.** ``asyncpg``/``redis.asyncio``/``httpx.AsyncClient``
   заменены синхронными ``psycopg``/``redis``/``httpx``; параллельность
   ``asyncio.gather`` — ``ThreadPoolExecutor`` (монолит WSGI-first, решение
   Д11, как и весь остальной порт).
4. **Кольца аудита и истории — в Redis, а не в памяти процесса.** У источника
   это были модульные ``deque`` — под gunicorn с 4 воркерами такое кольцо
   становится ЧЕТЫРЬМЯ разными кольцами, и админ видел бы разные ответы от
   запроса к запросу, а событие раскрытия паролей могло бы вовсе потеряться
   из выдачи. Используем ``LPUSH``/``LTRIM``/``LRANGE`` (атомарно, общее на
   все воркеры). Redis — не БД: кольцо переживает рестарт контейнера, но не
   ``FLUSHDB``, поэтому раскрытие креденшелов ДОПОЛНИТЕЛЬНО пишется в
   обычный лог (Loki), как и у источника.
5. **Rate-limit ``10/minute``** на раскрытие креденшелов у источника делал
   ``slowapi``; здесь — счётчик в том же Redis (``INCR`` + ``EXPIRE``),
   ключ на пользователя.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

MASKED_VALUE = "********"
REVEAL_TTL_SECONDS = 300      # рекомендованное окно видимости на клиенте
HEALTH_CACHE_TTL = 5.0        # сек — схлопывает параллельные вкладки админа
HEALTH_TIMEOUT = 2.5          # сек на одну проверку
AUDIT_RING_SIZE = 200
HISTORY_RING_SIZE = 30
REVEAL_RATE_LIMIT = 10        # раскрытий в минуту на пользователя (источник: 10/minute)

_AUDIT_KEY = "infra:audit:reveals"
_HISTORY_KEY = "infra:health:history:%s"
_HEALTH_CACHE_KEY = "infra:health:all"


class RateLimited(Exception):
    """429 — превышен лимит попыток раскрытия креденшелов."""


# ── Redis-кольца ───────────────────────────────────────────────────────────

def _redis():
    """Сырое подключение к тому же Redis, что и кэш Django. ``None``, если
    django_redis недоступен/не отвечает — все вызывающие ниже обязаны это
    пережить (кольца — вспомогательная телеметрия, они не должны ронять
    страницу)."""
    try:
        from django_redis import get_redis_connection

        return get_redis_connection("default")
    except Exception as exc:  # noqa: BLE001
        logger.warning("infrastructure: Redis недоступен (%s), кольца отключены", exc)
        return None


def _ring_push(key: str, payload: dict, maxlen: int) -> None:
    conn = _redis()
    if conn is None:
        return
    try:
        pipe = conn.pipeline()
        pipe.lpush(key, json.dumps(payload, default=str))
        pipe.ltrim(key, 0, maxlen - 1)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("infrastructure: не удалось записать в кольцо %s: %s", key, exc)


def _ring_read(key: str) -> list[dict]:
    conn = _redis()
    if conn is None:
        return []
    try:
        return [json.loads(raw) for raw in conn.lrange(key, 0, -1)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("infrastructure: не удалось прочитать кольцо %s: %s", key, exc)
        return []


def check_reveal_rate_limit(user_id: int | None) -> None:
    """Порт ``@limiter.limit("10/minute")``. Ключ на пользователя (у источника
    — на IP; за nginx у всех админов IP одинаковый, поэтому по пользователю
    точнее). Redis недоступен -> лимит не применяется, но и не блокирует."""
    conn = _redis()
    if conn is None:
        return
    key = f"infra:reveal:rate:{user_id}"
    try:
        hits = conn.incr(key)
        if hits == 1:
            conn.expire(key, 60)
        if hits > REVEAL_RATE_LIMIT:
            raise RateLimited("Слишком много попыток раскрытия — попробуйте через минуту")
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("infrastructure: rate-limit не сработал (%s)", exc)


# ── Сборка карточек ресурсов ───────────────────────────────────────────────

def _secret(value: str, reveal: bool) -> tuple[str, bool, bool]:
    if reveal:
        return value, False, bool(value)
    return (MASKED_VALUE if value else "", True, False)


def _field(key: str, label: str, value: str, *, secret: bool = False,
           reveal: bool = False) -> dict:
    displayed, masked, copyable = value, False, bool(value)
    if secret:
        displayed, masked, copyable = _secret(value, reveal)
    return {"key": key, "label": label, "value": displayed,
            "secret": secret, "masked": masked, "copyable": copyable}


def _db() -> dict:
    return settings.DATABASES["default"]


def _redis_url() -> str:
    return settings.CACHES["default"]["LOCATION"]


def _postgres_dsn() -> str:
    db = _db()
    user = quote_plus(str(db.get("USER", "")))
    password = quote_plus(str(db.get("PASSWORD", "")))
    return f"postgresql://{user}:{password}@{db.get('HOST')}:{db.get('PORT')}/{db.get('NAME')}"


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _minio_cli() -> str:
    return (f"mc alias set htqweb {_shell_quote(settings.S3_ENDPOINT)} "
            f"{_shell_quote(settings.S3_ACCESS_KEY)} {_shell_quote(settings.S3_SECRET_KEY)}")


def build_response(*, reveal: bool) -> dict:
    """Порт ``_build_response``. Ресурс ``mongo`` исключён (см. докстринг
    модуля, п.1)."""
    db = _db()
    redis_url = _redis_url()
    # У источника redis-креды считались секретом, только если URL их содержит
    # (``"@" in redis_url``) — сохранено буквально.
    redis_is_secret = "@" in redis_url

    resources = [
        {
            "id": "postgres",
            "name": "PostgreSQL",
            "kind": "database",
            "status": "configured",
            "summary": "Основная SQL БД платформы",
            "endpoint": f"{db.get('HOST')}:{db.get('PORT')}",
            "database": db.get("NAME"),
            "credentials": [
                _field("host", "Host", str(db.get("HOST", ""))),
                _field("port", "Port", str(db.get("PORT", ""))),
                _field("database", "Database", str(db.get("NAME", ""))),
                _field("username", "Username", str(db.get("USER", ""))),
                _field("password", "Password", str(db.get("PASSWORD", "")), secret=True, reveal=reveal),
                _field("dsn", "Connection URI", _postgres_dsn(), secret=True, reveal=reveal),
                _field("cli", "psql", f"psql {_shell_quote(_postgres_dsn())}", secret=True, reveal=reveal),
            ],
            "links": [{"label": "Django admin", "url": settings.DB_ADMIN_URL, "external": False}],
        },
        {
            "id": "redis",
            "name": "Redis",
            "kind": "cache",
            "status": "configured",
            "summary": "Кеш, брокер Celery и служебные каналы",
            "endpoint": redis_url,
            "database": None,
            "credentials": [
                _field("url", "Redis URL", redis_url, secret=redis_is_secret, reveal=reveal),
                _field("cli", "redis-cli", f"redis-cli -u {_shell_quote(redis_url)}",
                       secret=redis_is_secret, reveal=reveal),
            ],
            "links": [],
        },
        {
            "id": "minio",
            "name": "MinIO / S3",
            "kind": "object-storage",
            "status": "configured",
            "summary": "S3-совместимое хранилище файлов",
            "endpoint": settings.S3_ENDPOINT,
            "database": settings.S3_BUCKET,
            "credentials": [
                _field("endpoint", "Endpoint", settings.S3_ENDPOINT),
                _field("bucket", "Bucket (cms)", settings.S3_BUCKET),
                _field("media_bucket", "Bucket (media)", settings.MEDIA_S3_BUCKET),
                _field("region", "Region", settings.S3_REGION),
                _field("access_key", "Access key", settings.S3_ACCESS_KEY),
                _field("secret_key", "Secret key", settings.S3_SECRET_KEY, secret=True, reveal=reveal),
                _field("cli", "mc alias set", _minio_cli(), secret=True, reveal=reveal),
            ],
            "links": [{"label": "MinIO Console", "url": settings.MINIO_CONSOLE_URL, "external": True}],
        },
    ]

    now = datetime.now(timezone.utc)
    return {
        "credentials_visible": reveal,
        "issued_at": now.isoformat(),
        "environment": settings.SERVICE_ENV,
        "reveal_expires_at": (now + timedelta(seconds=REVEAL_TTL_SECONDS)).isoformat() if reveal else None,
        "reveal_ttl_seconds": REVEAL_TTL_SECONDS if reveal else None,
        "resources": resources,
    }


# ── Health-checks ──────────────────────────────────────────────────────────

def _check_postgres() -> tuple[str, str]:
    """Отдельное psycopg-подключение, а НЕ ``django.db.connection``: проверка
    крутится в пуле потоков, а Django-подключение потоко-локально — своё
    подключение на поток пришлось бы ещё и аккуратно закрывать. Плюс так
    задаётся честный ``connect_timeout`` (порт ``asyncpg.connect(timeout=)``
    источника)."""
    import psycopg

    db = _db()
    conn = psycopg.connect(
        host=db.get("HOST"), port=db.get("PORT"), user=db.get("USER"),
        password=db.get("PASSWORD"), dbname=db.get("NAME"),
        connect_timeout=int(HEALTH_TIMEOUT) or 1,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    finally:
        conn.close()
    return "ok", "SELECT 1 OK"


def _check_redis() -> tuple[str, str]:
    import redis as redis_lib

    client = redis_lib.Redis.from_url(
        _redis_url(), socket_timeout=HEALTH_TIMEOUT, socket_connect_timeout=HEALTH_TIMEOUT,
    )
    try:
        pong = client.ping()
    finally:
        client.close()
    return ("ok", "PONG") if pong else ("error", "no pong")


def _check_minio() -> tuple[str, str]:
    parsed = urlparse(settings.S3_ENDPOINT)
    base = f"{parsed.scheme or 'http'}://{parsed.netloc or parsed.path}"
    resp = httpx.get(f"{base}/minio/health/live", timeout=HEALTH_TIMEOUT)
    if resp.status_code == 200:
        return "ok", "live"
    return "error", f"HTTP {resp.status_code}"


HEALTH_CHECKS: dict[str, Callable[[], tuple[str, str]]] = {
    "postgres": _check_postgres,
    "redis": _check_redis,
    "minio": _check_minio,
}


def _record_history(resource_id: str, status: str, latency_ms: int | None, at: datetime) -> None:
    _ring_push(_HISTORY_KEY % resource_id,
               {"at": at.isoformat(), "status": status, "latency_ms": latency_ms},
               HISTORY_RING_SIZE)


def run_health(resource_id: str) -> dict:
    """Порт ``_run_health``."""
    checked_at = datetime.now(timezone.utc)
    check = HEALTH_CHECKS.get(resource_id)
    if check is None:
        return {"id": resource_id, "status": "error", "latency_ms": None,
                "message": "unknown resource", "checked_at": checked_at.isoformat()}
    started = time.perf_counter()
    try:
        status, message = check()
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - started) * 1000)
        _record_history(resource_id, "error", latency, checked_at)
        return {"id": resource_id, "status": "error", "latency_ms": latency,
                "message": f"{type(exc).__name__}: {exc}"[:200],
                "checked_at": checked_at.isoformat()}
    latency = int((time.perf_counter() - started) * 1000)
    _record_history(resource_id, status, latency, checked_at)
    return {"id": resource_id, "status": status, "latency_ms": latency,
            "message": message, "checked_at": checked_at.isoformat()}


def health_all(*, use_cache: bool = True) -> dict:
    """Порт ``_cached_health_all``: 5-секундный кэш, чтобы несколько
    открытых вкладок админа не били по инфраструктуре пачкой. Кэш — в Redis
    (общий на воркеры), а не в памяти процесса, по той же причине, что и
    кольца (см. докстринг модуля, п.4)."""
    from django.core.cache import cache

    if use_cache:
        cached = cache.get(_HEALTH_CACHE_KEY)
        if cached is not None:
            return cached

    with ThreadPoolExecutor(max_workers=len(HEALTH_CHECKS)) as pool:
        results = list(pool.map(run_health, HEALTH_CHECKS.keys()))

    payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "results": results}
    cache.set(_HEALTH_CACHE_KEY, payload, int(HEALTH_CACHE_TTL))
    return payload


def invalidate_health_cache() -> None:
    """Порт ``_health_cache["at"] = 0.0`` после ручной проверки одного
    ресурса — чтобы следующий общий refetch показал свежий результат."""
    from django.core.cache import cache

    cache.delete(_HEALTH_CACHE_KEY)


def health_history() -> dict:
    return {"history": {rid: _ring_read(_HISTORY_KEY % rid) for rid in HEALTH_CHECKS}}


# ── Аудит раскрытия креденшелов ────────────────────────────────────────────

def record_reveal(*, user_id, email, ip, user_agent) -> None:
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "email": email,
        "ip": ip,
        "user_agent": (user_agent or "")[:200],
        "ttl_seconds": REVEAL_TTL_SECONDS,
    }
    _ring_push(_AUDIT_KEY, event, AUDIT_RING_SIZE)
    # Кольцо живёт в Redis и переживает рестарт, но не FLUSHDB — раскрытие
    # паролей дублируем в обычный лог (Loki), как и источник.
    logger.info(
        "infrastructure_credentials_revealed: user_id=%s email=%s ip=%s ua=%s",
        user_id, email, ip, event["user_agent"],
    )


def reveal_audit() -> dict:
    """Порт ``audit_reveals``: новые события первыми. ``LPUSH`` уже кладёт
    новое в голову, так что ``reversed()`` источника здесь не нужен."""
    return {"events": _ring_read(_AUDIT_KEY)}


def client_ip(request) -> str | None:
    """Порт ``slowapi.util.get_remote_address``, но с учётом того, что в этой
    инсталляции backend всегда стоит за nginx: без разбора X-Forwarded-For у
    ВСЕХ событий аудита был бы IP гейтвея."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def verify_admin_password(token, password: str) -> bool:
    """Повторная аутентификация админа перед раскрытием паролей.

    Источник ходил по сети в user-service (``POST /api/users/v1/token/``) и
    сверял, что вернувшийся токен принадлежит ТОМУ ЖЕ пользователю и он всё
    ещё админ. В монолите сети нет — зовём соседа через его interface
    (единственный разрешённый способ, apps/core/tests/test_app_isolation.py).
    Проверка «тот же пользователь» становится тривиальной: мы сверяем пароль
    именно для ``token.user_id``, а не для присланного логина, так что
    подставить чужой аккаунт нечем.

    Импорт локальный: ``apps.users.interface`` сам импортирует
    ``apps.core.services`` — на уровне модуля это замкнуло бы импорт core на
    users при старте Django."""
    from apps.users import interface as users_interface

    return users_interface.verify_password(token.user_id, password)
