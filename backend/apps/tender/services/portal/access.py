"""Доступ к порталу поставщика: токен ссылки, устройство, Origin, IP, журнал
(T3.2; план этапа 3, §1; мастер-план T-21…T-26).

Портал — анонимный контур (``api_view(auth=None)``). Доступ даёт только пара
«токен ссылки + секрет устройства в cookie»:

- ``resolve(request, token)`` — токен → приглашение в схеме компании запроса
  (поддомен). Неизвестный, отозванный, перевыпущенный токен и тендер в
  черновике — ОДИНАКОВЫЙ 404: тело не различает причины. Здесь же лимиты
  запросов на токен и на IP (429 ``E-RATE-01`` + ``Retry-After``);
- ``require_device(request, token) -> PortalContext`` — первая строка каждой
  ручки портала, кроме промежуточной карточки и ``bind``: cookie этого
  устройства должна быть привязана к приглашению, иначе 403 ``E-TND-06``.
  У небезопасных методов — ещё ``check_origin`` и тело только JSON (415);
- ``record_event(ctx, kind, meta)`` — строка журнала ``PortalEvent`` в той
  же транзакции, что действие.

Сырой токен и секрет устройства не логируются и не попадают ни в журнал, ни
в ответ: в БД — только SHA-256. IP — только ``X-Real-IP`` шлюза (без него —
``REMOTE_ADDR``), никогда ``X-Forwarded-For``: его подделывает клиент.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, ValidationError

from apps.companies import interface as companies
from apps.tender.models import (
    DeviceBinding,
    Invitation,
    PortalEvent,
    Tender,
    TenderStatus,
)
from htqweb import ratelimit
from htqweb.errors import DomainError
from htqweb.tenancy import current_company_or_none

COOKIE_SECURE_NAME = "__Secure-tender_device"
COOKIE_INSECURE_NAME = "tender_device"
COOKIE_PATH = "/api/tender/v1/supplier/"
#: Cookie живёт до конца приёма + 30 дней: поставщик смотрит итог (TND-035).
COOKIE_TAIL = timedelta(days=30)
COOKIE_MIN_AGE = 24 * 3600

UA_MAX = 512
#: Токен ``secrets.token_urlsafe(32)`` — 43 символа; запас на смену длины.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

#: Окна лимитов; сами лимиты — ``settings.TENDER_PORTAL_*_LIMIT``.
MINUTE, HOUR = 60, 3600

#: Методы без побочных эффектов — без проверки Origin и тела.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
JSON_TYPE = "application/json"
MULTIPART_TYPE = "multipart/form-data"

#: Ключи, которые в журнал не пишутся ни при каких условиях.
_SECRET_KEYS = ("token", "secret", "hash", "cookie", "password")


@dataclass(frozen=True)
class PortalContext:
    """Кто пришёл: приглашение, его тендер, привязка устройства, IP и браузер
    запроса — то, с чем работают сервисы портала (``offers.py``, ``files``)."""

    invitation: Invitation
    tender: Tender
    binding: DeviceBinding | None
    ip: str | None
    user_agent: str


# ── ошибки ──────────────────────────────────────────────────────────────

def dead_link() -> DomainError:
    """Один ответ на любую нерабочую ссылку — причина не раскрывается."""
    return DomainError("E-NOT-FOUND", "Ссылка недействительна.", status=404)


def dead_file() -> DomainError:
    return DomainError("E-NOT-FOUND", "Файл не найден.", status=404)


def device_refused() -> DomainError:
    return DomainError(
        "E-TND-06", "Ссылка открыта на другом устройстве. Попросите закупщика сбросить "
                    "привязку устройства.", status=403, details={"rebind": "otp"})


def rate_limited(bucket: str, key: str, window: int) -> DomainError:
    seconds = ratelimit.retry_after(bucket, key, window)
    return DomainError("E-RATE-01", f"Слишком много запросов. Повторите через {seconds} с.",
                       status=429, details={"retry_after": seconds},
                       headers={"Retry-After": str(seconds)})


# ── запрос ──────────────────────────────────────────────────────────────

def _ip_or_none(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(request) -> str | None:
    """IP поставщика: ``X-Real-IP`` (ставит nginx, затирая присланный), без
    шлюза (стенд, тесты) — ``REMOTE_ADDR``. ``X-Forwarded-For`` не читается."""
    return (_ip_or_none(request.META.get("HTTP_X_REAL_IP"))
            or _ip_or_none(request.META.get("REMOTE_ADDR")))


def user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:UA_MAX]


def company_slug(request) -> str | None:
    company = getattr(request, "company", None) or {}
    return company.get("slug") or current_company_or_none()


def _limit(bucket: str, key: str, limit: int, window: int) -> None:
    if not ratelimit.hit(bucket, key, limit=limit, window=window):
        raise rate_limited(bucket, key, window)


def throttle_bind(token: str) -> None:
    """``bind`` — 10 в час на токен: перебор устройств по одной ссылке."""
    _limit("tender_portal_bind", token, settings.TENDER_PORTAL_BIND_LIMIT, HOUR)


# ── токен → приглашение ─────────────────────────────────────────────────

def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def resolve(request, token: str) -> tuple[Invitation, Tender]:
    """Приглашение по токену в схеме компании запроса — или единый 404.

    Лимиты считаются ДО поиска: перебор токенов упирается в лимит по IP,
    а не в базу."""
    ip = client_ip(request)
    if ip:
        _limit("tender_portal_ip", ip, settings.TENDER_PORTAL_IP_LIMIT, MINUTE)
    if not company_slug(request) or not _TOKEN.match(token or ""):
        raise dead_link()
    _limit("tender_portal_token", token, settings.TENDER_PORTAL_TOKEN_LIMIT, MINUTE)
    invitation = (Invitation.objects.select_related("tender", "tender__request")
                  .filter(token_hash=digest(token), revoked_at__isnull=True).first())
    if invitation is None or invitation.tender.status == TenderStatus.DRAFT:
        raise dead_link()
    return invitation, invitation.tender


# ── устройство ──────────────────────────────────────────────────────────

def cookie_name() -> str:
    return COOKIE_INSECURE_NAME if settings.TENDER_PORTAL_INSECURE_COOKIE else COOKIE_SECURE_NAME


def device_secret(request) -> str | None:
    """Секрет устройства из cookie — только правильного вида: мусор не
    хэшируется и не ищется."""
    value = request.COOKIES.get(cookie_name()) or ""
    return value if _SECRET.match(value) else None


def active_binding(invitation: Invitation, secret: str | None) -> DeviceBinding | None:
    if not secret:
        return None
    return DeviceBinding.objects.filter(invitation=invitation, secret_hash=digest(secret),
                                        revoked_at__isnull=True).first()


def cookie_expires(tender: Tender) -> datetime:
    end = tender.deadline_at or timezone.now()
    return end + COOKIE_TAIL


def set_device_cookie(response, secret: str, expires: datetime) -> None:
    """``HttpOnly; Secure; SameSite=Strict; Path=/api/tender/v1/supplier/``.
    На стенде без HTTPS (``TENDER_PORTAL_INSECURE_COOKIE``) — без Secure и без
    префикса ``__Secure-``: браузер такую cookie по http не примет."""
    max_age = max(COOKIE_MIN_AGE, int((expires - timezone.now()).total_seconds()))
    insecure = bool(settings.TENDER_PORTAL_INSECURE_COOKIE)
    response.set_cookie(cookie_name(), secret, max_age=max_age, path=COOKIE_PATH,
                        secure=not insecure, httponly=True, samesite="Strict")


def clear_device_cookie(response) -> None:
    response.delete_cookie(cookie_name(), path=COOKIE_PATH, samesite="Strict")


# ── Origin и тело ───────────────────────────────────────────────────────

def _allowed_roots() -> dict[str, set[str]]:
    """Корень хоста → допустимые схемы ``Origin``: корень ``PUBLIC_BASE_URL``
    — только его схема (на бою https); ``localhost`` — http и https, и только
    при ``DEBUG`` (стенд разработчика)."""
    base = urlsplit((settings.PUBLIC_BASE_URL or "").strip())
    roots: dict[str, set[str]] = {}
    if base.hostname and base.scheme:
        roots[base.hostname.lower()] = {base.scheme.lower()}
    if settings.DEBUG:
        roots.setdefault("localhost", set()).update({"http", "https"})
    return roots


def check_origin(request) -> None:
    """``Origin`` обязателен и принадлежит хосту компании запроса: адрес
    ``companies.public_url`` либо метка поддомена, которая резолвится в эту
    компанию, при корне из ``PUBLIC_BASE_URL`` (или ``localhost`` — только
    при ``DEBUG``). Иначе 403 ``E-ACC-01``: чужая страница не отправит форму
    от имени поставщика, даже если браузер пошлёт его cookie."""
    refused = DomainError("E-ACC-01", "Запрос отклонён: неизвестный источник.", status=403)
    raw = (request.META.get("HTTP_ORIGIN") or "").strip()
    slug = company_slug(request)
    if not raw or raw == "null" or not slug:
        raise refused
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if not parts.scheme or not host:
        raise refused
    canonical = companies.public_url(slug)
    if canonical:
        own = urlsplit(canonical)
        if parts.scheme == own.scheme and parts.netloc.lower() == own.netloc.lower():
            return
    label, _, root = host.partition(".")
    # Схема — как у корня: http://<метка>.<корень> при https-корне — чужой
    # источник (страницу по http подменит любой на пути).
    if parts.scheme.lower() in _allowed_roots().get(root, set()):
        company = companies.resolve_host_label(label)
        if company and company.get("slug") == slug:
            return
    raise refused


def check_body(request, *, multipart: bool = False) -> None:
    """Тело небезопасного запроса — только JSON (415); ``multipart/form-data``
    — только там, где грузят файл (``multipart=True``). DELETE без тела
    проверку проходит."""
    content_type = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    if request.method == "DELETE" and not request.body:
        return
    allowed = (JSON_TYPE, MULTIPART_TYPE) if multipart else (JSON_TYPE,)
    if content_type not in allowed:
        raise DomainError("E-VAL-02", "Тело запроса — только application/json.", status=415)


def check_write(request, *, multipart: bool = False) -> None:
    """Origin и тело — для любого метода с побочным эффектом."""
    if request.method not in SAFE_METHODS:
        check_origin(request)
        check_body(request, multipart=multipart)


def parse_body(request, schema: type[BaseModel]) -> BaseModel:
    """Тело JSON по схеме — ПОСЛЕ ``require_device``: чужое устройство
    получает 403, не узнав, разбирается ли его тело, а ошибка тела своего —
    422 ``E-VAL-01`` в конверте портала (поле — путь через точку)."""
    try:
        return schema.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        fields = [{"field": ".".join(str(part) for part in error["loc"]) or "body",
                   "message": error["msg"]} for error in exc.errors(include_input=False)]
        raise DomainError("E-VAL-01", "Проверьте заполнение полей.", fields=fields) from None


def require_device(request, token: str, *, multipart: bool = False) -> PortalContext:
    """Первая строка каждой ручки портала, кроме карточки и ``bind``:
    токен → приглашение, cookie этого устройства привязана к нему.
    ``multipart`` — ручка загрузки файла."""
    check_write(request, multipart=multipart)
    invitation, tender = resolve(request, token)
    binding = active_binding(invitation, device_secret(request))
    if binding is None:
        raise device_refused()
    return PortalContext(invitation=invitation, tender=tender, binding=binding,
                         ip=client_ip(request), user_agent=user_agent(request))


# ── журнал ──────────────────────────────────────────────────────────────

def _clean(value):
    """Рекурсивно: словари без ключей, похожих на секреты, списки — поэлементно."""
    if isinstance(value, dict):
        return {key: _clean(inner) for key, inner in value.items()
                if not any(part in str(key).lower() for part in _SECRET_KEYS)}
    if isinstance(value, (list, tuple)):
        return [_clean(inner) for inner in value]
    return value


def _clean_meta(meta: dict | None) -> dict:
    """Метаданные события без ключей, похожих на секреты (токен, хэш,
    cookie, пароль) на любой глубине — на случай, если вызывающий положит
    лишнее."""
    return _clean(meta or {})


def log_event(invitation: Invitation, kind: str, *, ip: str | None = None,
              user_agent: str = "", meta: dict | None = None) -> PortalEvent:
    return PortalEvent.objects.create(invitation=invitation, kind=kind, ip=ip,
                                      user_agent=(user_agent or "")[:UA_MAX],
                                      meta=_clean_meta(meta))


def record_event(ctx: PortalContext, kind: str, meta: dict | None = None) -> PortalEvent:
    """Событие портала от имени поставщика (IP и браузер — из контекста).
    Сигнатура ``(ctx, kind, meta)``: сервис предложения получает
    ``lambda kind, meta: record_event(ctx, kind, meta)``."""
    return log_event(ctx.invitation, kind, ip=ctx.ip, user_agent=ctx.user_agent, meta=meta)
