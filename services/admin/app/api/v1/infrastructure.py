"""Infrastructure admin endpoints.

The safe endpoint returns masked connection data. Plaintext credentials are
returned only after the current admin re-enters their password.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import quote_plus, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.logging import get_logger
from app.core.settings import settings


router = APIRouter(prefix="/api/admin/v1/infrastructure", tags=["admin-infrastructure"])
security = HTTPBearer(auto_error=False)
MASKED_VALUE = "********"
REVEAL_TTL_SECONDS = 300  # server-side recommended visibility window
HEALTH_CACHE_TTL = 5.0  # seconds — coalesce concurrent admin tabs
AUDIT_RING_SIZE = 200
HISTORY_RING_SIZE = 30
log = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)

_audit_ring: deque[dict[str, Any]] = deque(maxlen=AUDIT_RING_SIZE)
_history_rings: dict[str, deque[dict[str, Any]]] = {}


class CredentialField(BaseModel):
    key: str
    label: str
    value: str
    secret: bool = False
    masked: bool = False
    copyable: bool = True


class ResourceLink(BaseModel):
    label: str
    url: str
    external: bool = True


class ManagedResource(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    summary: str
    endpoint: str
    database: str | None = None
    credentials: list[CredentialField]
    links: list[ResourceLink] = []


class InfrastructureResponse(BaseModel):
    credentials_visible: bool
    issued_at: datetime
    environment: str
    reveal_expires_at: datetime | None = None
    reveal_ttl_seconds: int | None = None
    resources: list[ManagedResource]


class RevealCredentialsRequest(BaseModel):
    password: str = Field(min_length=1)


class HealthResult(BaseModel):
    id: str
    status: str  # "ok" | "error"
    latency_ms: int | None = None
    message: str = ""
    checked_at: datetime


class HealthCheckResponse(BaseModel):
    checked_at: datetime
    results: list[HealthResult]


class HealthHistoryPoint(BaseModel):
    at: datetime
    status: str
    latency_ms: int | None = None


class HealthHistoryResponse(BaseModel):
    history: dict[str, list[HealthHistoryPoint]]


class AuditEvent(BaseModel):
    at: datetime
    user_id: int | str | None = None
    email: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    ttl_seconds: int | None = None


class AuditResponse(BaseModel):
    events: list[AuditEvent]


def _decode_access_token(token: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "algorithms": [settings.jwt_algorithm],
        "options": {"verify_exp": True},
    }
    if settings.jwt_issuer:
        kwargs["issuer"] = settings.jwt_issuer
    return jwt.decode(token, settings.jwt_secret, **kwargs)


def _is_admin_payload(payload: dict[str, Any]) -> bool:
    return bool(payload.get("is_admin") or payload.get("is_staff") or payload.get("is_superuser"))


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = _decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("token_type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token required")
    if not _is_admin_payload(payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return payload


async def _reauthenticate_admin(payload: dict[str, Any], password: str) -> None:
    login_id = str(payload.get("email") or payload.get("username") or "")
    if not login_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin identity is missing")

    user_service_url = settings.user_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{user_service_url}/api/users/v1/token/",
                json={"email": login_id, "password": password},
            )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service is unavailable",
        )

    if resp.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")
    if resp.status_code != status.HTTP_200_OK:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin re-authentication failed")

    access_token = resp.json().get("access")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Token response is invalid")

    try:
        verified = _decode_access_token(access_token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Token response is invalid")

    if verified.get("user_id") != payload.get("user_id") or not _is_admin_payload(verified):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin re-authentication failed")


def _secret(value: str, reveal: bool) -> tuple[str, bool, bool]:
    if reveal:
        return value, False, bool(value)
    return (MASKED_VALUE if value else "", True, False)


def _field(key: str, label: str, value: str, *, secret: bool = False, reveal: bool = False) -> CredentialField:
    displayed = value
    masked = False
    copyable = bool(value)
    if secret:
        displayed, masked, copyable = _secret(value, reveal)
    return CredentialField(
        key=key,
        label=label,
        value=displayed,
        secret=secret,
        masked=masked,
        copyable=copyable,
    )


def _postgres_dsn() -> str:
    user = quote_plus(settings.db_user)
    password = quote_plus(settings.db_password)
    return f"postgresql://{user}:{password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"


def _mongo_uri() -> str:
    if settings.mongo_uri:
        return settings.mongo_uri
    user = quote_plus(settings.mongo_user)
    password = quote_plus(settings.mongo_password)
    return (
        f"mongodb://{user}:{password}@{settings.mongo_host}:{settings.mongo_port}/"
        f"{settings.mongo_database}?authSource=admin"
    )


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in value):
        return value
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def _postgres_cli() -> str:
    return f"psql {_shell_quote(_postgres_dsn())}"


def _mongo_cli() -> str:
    return f"mongosh {_shell_quote(_mongo_uri())}"


def _redis_cli() -> str:
    return f"redis-cli -u {_shell_quote(settings.redis_url)}"


def _minio_cli() -> str:
    return (
        f"mc alias set htqweb {_shell_quote(settings.minio_endpoint)} "
        f"{_shell_quote(settings.minio_root_user)} {_shell_quote(settings.minio_root_password)}"
    )


def _build_response(*, reveal: bool) -> InfrastructureResponse:
    resources = [
        ManagedResource(
            id="postgres",
            name="PostgreSQL / PgBouncer",
            kind="database",
            status="configured",
            summary="Основная SQL БД платформы",
            endpoint=f"{settings.db_host}:{settings.db_port}",
            database=settings.db_name,
            credentials=[
                _field("host", "Host", settings.db_host),
                _field("port", "Port", str(settings.db_port)),
                _field("database", "Database", settings.db_name),
                _field("username", "Username", settings.db_user),
                _field("password", "Password", settings.db_password, secret=True, reveal=reveal),
                _field("dsn", "Connection URI", _postgres_dsn(), secret=True, reveal=reveal),
                _field("cli", "psql", _postgres_cli(), secret=True, reveal=reveal),
            ],
            links=[ResourceLink(label="sqladmin", url=settings.sqladmin_url)],
        ),
        ManagedResource(
            id="mongo",
            name="MongoDB",
            kind="document-database",
            status="configured",
            summary="NoSQL хранилище HR-документов",
            endpoint=f"{settings.mongo_host}:{settings.mongo_port}",
            database=settings.mongo_database,
            credentials=[
                _field("host", "Host", settings.mongo_host),
                _field("port", "Port", str(settings.mongo_port)),
                _field("database", "Database", settings.mongo_database),
                _field("username", "Username", settings.mongo_user),
                _field("password", "Password", settings.mongo_password, secret=True, reveal=reveal),
                _field("uri", "Mongo URI", _mongo_uri(), secret=True, reveal=reveal),
                _field("cli", "mongosh", _mongo_cli(), secret=True, reveal=reveal),
            ],
            links=[ResourceLink(label="Mongo Admin", url=settings.mongo_admin_url)],
        ),
        ManagedResource(
            id="redis",
            name="Redis",
            kind="cache",
            status="configured",
            summary="Очереди, кеш и служебные каналы",
            endpoint=settings.redis_url,
            credentials=[
                _field("url", "Redis URL", settings.redis_url, secret="@" in settings.redis_url, reveal=reveal),
                _field("cli", "redis-cli", _redis_cli(), secret="@" in settings.redis_url, reveal=reveal),
            ],
            links=[],
        ),
        ManagedResource(
            id="minio",
            name="MinIO / S3",
            kind="object-storage",
            status="configured",
            summary="S3-совместимое хранилище файлов",
            endpoint=settings.minio_endpoint,
            database=settings.s3_bucket,
            credentials=[
                _field("endpoint", "Endpoint", settings.minio_endpoint),
                _field("bucket", "Bucket", settings.s3_bucket),
                _field("region", "Region", settings.s3_region),
                _field("access_key", "Access key", settings.minio_root_user),
                _field("secret_key", "Secret key", settings.minio_root_password, secret=True, reveal=reveal),
                _field("cli", "mc alias set", _minio_cli(), secret=True, reveal=reveal),
            ],
            links=[ResourceLink(label="MinIO Console", url=settings.minio_console_url)],
        ),
    ]
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=REVEAL_TTL_SECONDS) if reveal else None
    return InfrastructureResponse(
        credentials_visible=reveal,
        issued_at=now,
        environment=settings.service_env,
        reveal_expires_at=expires_at,
        reveal_ttl_seconds=REVEAL_TTL_SECONDS if reveal else None,
        resources=resources,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


HEALTH_TIMEOUT = 2.5


async def _check_postgres() -> tuple[str, str]:
    import asyncpg

    conn = await asyncpg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        timeout=HEALTH_TIMEOUT,
    )
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()
    return "ok", "SELECT 1 OK"


async def _check_redis() -> tuple[str, str]:
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, socket_timeout=HEALTH_TIMEOUT, socket_connect_timeout=HEALTH_TIMEOUT)
    try:
        pong = await client.ping()
    finally:
        await client.close()
    return ("ok", "PONG") if pong else ("error", "no pong")


async def _check_mongo() -> tuple[str, str]:
    fut = asyncio.open_connection(settings.mongo_host, settings.mongo_port)
    reader, writer = await asyncio.wait_for(fut, timeout=HEALTH_TIMEOUT)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return "ok", f"TCP {settings.mongo_host}:{settings.mongo_port} reachable"


async def _check_minio() -> tuple[str, str]:
    parsed = urlparse(settings.minio_endpoint)
    base = f"{parsed.scheme or 'http'}://{parsed.netloc or parsed.path}"
    async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
        resp = await client.get(f"{base}/minio/health/live")
    if resp.status_code == 200:
        return "ok", "live"
    return "error", f"HTTP {resp.status_code}"


_HEALTH_CHECKS = {
    "postgres": _check_postgres,
    "redis": _check_redis,
    "mongo": _check_mongo,
    "minio": _check_minio,
}


def _record_history(resource_id: str, status_: str, latency_ms: int | None, at: datetime) -> None:
    ring = _history_rings.setdefault(resource_id, deque(maxlen=HISTORY_RING_SIZE))
    ring.append({"at": at, "status": status_, "latency_ms": latency_ms})


async def _run_health(resource_id: str) -> HealthResult:
    checked_at = datetime.now(timezone.utc)
    check = _HEALTH_CHECKS.get(resource_id)
    if check is None:
        return HealthResult(id=resource_id, status="error", message="unknown resource", checked_at=checked_at)
    started = time.perf_counter()
    try:
        status_, message = await check()
        latency = int((time.perf_counter() - started) * 1000)
        _record_history(resource_id, status_, latency, checked_at)
        return HealthResult(id=resource_id, status=status_, latency_ms=latency, message=message, checked_at=checked_at)
    except Exception as exc:
        latency = int((time.perf_counter() - started) * 1000)
        _record_history(resource_id, "error", latency, checked_at)
        return HealthResult(
            id=resource_id,
            status="error",
            latency_ms=latency,
            message=f"{type(exc).__name__}: {exc}"[:200],
            checked_at=checked_at,
        )


_health_cache: dict[str, Any] = {"at": 0.0, "response": None, "lock": asyncio.Lock()}


async def _cached_health_all() -> HealthCheckResponse:
    now_mono = time.monotonic()
    cached = _health_cache.get("response")
    if cached is not None and now_mono - _health_cache["at"] < HEALTH_CACHE_TTL:
        return cached
    async with _health_cache["lock"]:
        now_mono = time.monotonic()
        cached = _health_cache.get("response")
        if cached is not None and now_mono - _health_cache["at"] < HEALTH_CACHE_TTL:
            return cached
        results = await asyncio.gather(*[_run_health(rid) for rid in _HEALTH_CHECKS.keys()])
        resp = HealthCheckResponse(checked_at=datetime.now(timezone.utc), results=list(results))
        _health_cache["response"] = resp
        _health_cache["at"] = time.monotonic()
        return resp


@router.get("/health-check", response_model=HealthCheckResponse)
async def health_check_all(
    response: Response,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> HealthCheckResponse:
    _no_store(response)
    return await _cached_health_all()


@router.post("/{resource_id}/health-check", response_model=HealthResult)
async def health_check_one(
    resource_id: str,
    response: Response,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> HealthResult:
    _no_store(response)
    if resource_id not in _HEALTH_CHECKS:
        raise HTTPException(status_code=404, detail="Unknown resource")
    result = await _run_health(resource_id)
    _health_cache["at"] = 0.0  # invalidate batch cache so next refetch reflects manual check
    return result


@router.get("/", response_model=InfrastructureResponse)
async def get_infrastructure(
    response: Response,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> InfrastructureResponse:
    _no_store(response)
    return _build_response(reveal=False)


@router.post("/credentials/reveal", response_model=InfrastructureResponse)
@limiter.limit("10/minute")
async def reveal_credentials(
    request: Request,
    body: RevealCredentialsRequest,
    response: Response,
    admin_payload: Annotated[dict[str, Any], Depends(require_admin)],
) -> InfrastructureResponse:
    await _reauthenticate_admin(admin_payload, body.password)
    event = {
        "at": datetime.now(timezone.utc),
        "user_id": admin_payload.get("user_id"),
        "email": admin_payload.get("email"),
        "ip": get_remote_address(request),
        "user_agent": request.headers.get("user-agent", "")[:200],
        "ttl_seconds": REVEAL_TTL_SECONDS,
    }
    _audit_ring.append(event)
    log.info("infrastructure_credentials_revealed", **{k: v for k, v in event.items() if k != "at"})
    _no_store(response)
    return _build_response(reveal=True)


@router.get("/audit/reveals", response_model=AuditResponse)
async def audit_reveals(
    response: Response,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> AuditResponse:
    _no_store(response)
    events = [AuditEvent(**ev) for ev in reversed(_audit_ring)]
    return AuditResponse(events=events)


@router.get("/health-history", response_model=HealthHistoryResponse)
async def health_history(
    response: Response,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> HealthHistoryResponse:
    _no_store(response)
    out: dict[str, list[HealthHistoryPoint]] = {}
    for rid, ring in _history_rings.items():
        out[rid] = [HealthHistoryPoint(**p) for p in ring]
    return HealthHistoryResponse(history=out)
