"""ShareLinkService — порт services/hr/app/services/share_link_service.py.

Функции, а не класс (та же конвенция порта, что department_service.py/
org_service.py/… — исходник был class-based только из-за DI асинхронной
SQLAlchemy-сессии, здесь синхронный Django ORM без сессии).

Security model — буквальный порт докстринга исходника:
- Raw token генерируется ``secrets.token_urlsafe(32)`` (>=256 бит энтропии).
- В БД лежит только SHA-256(token) (``token_hash``); raw token возвращается
  вызывающему POST /share-links/ РОВНО один раз и никогда не персистится.
- Валидация токена хеширует входящий URL-параметр и ищет по ``token_hash``.
- Каждое открытие/отказ/отзыв дописывает строку в ``hr_share_link_audit``.

Отличие от исходника (``consume_link``): исходник намеренно держит ДВЕ копии
пайплайна валидации — ``_resolve_and_validate`` (общий, используется
``consume_employee_link``) и инлайновую копию внутри ``consume_link`` —
докстринг объясняет это желанием видеть будущее расхождение веток. На
сегодняшний день обе копии проверяют РОВНО одно и то же (просто с разным
``expected_target``), поэтому порт использует один общий
``_resolve_and_validate(expected_target=...)`` для обеих публичных consume-
функций — то же наблюдаемое поведение, без дублирования 60 строк.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.hr.models import ShareableLink, ShareLinkAudit
from apps.hr.services import employee_card_service as card_svc
from apps.hr.services import employee_service as emp_svc
from apps.hr.services import org_service

PII_FIELDS = (
    "email",
    "phone",
    "manager_email",
    "manager_phone",
    "salary",
    "iin",
    "birthday",
    "home_address",
)

NESTED_HOLDER_PII_FIELDS = PII_FIELDS + ("holder_email", "holder_phone")


class LinkNotFound(Exception):
    """404 "Link not found"."""


class TargetEmployeeRequired(Exception):
    """422 "target_employee_id is required when target_type='employee'"."""


class LinkRevoked(Exception):
    """410 "This link has been revoked"."""


class LinkAlreadyUsed(Exception):
    """410 "This one-time link has already been used"."""


class LinkExpired(Exception):
    """410 "This link has expired"."""


class LinkInactive(Exception):
    """410 "This link is no longer active"."""


class EmployeeLinkGone(Exception):
    """410 "The employee referenced by this link no longer exists"."""


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest. Детерминированно; без соли — токен уже
    высокоэнтропийный сам по себе."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    """43-символьный URL-safe токен с >=256 бит энтропии."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class CreatedLink:
    """Оборачивает свежесозданную ссылку вместе с её одноразовым raw token."""

    link: ShareableLink
    raw_token: str


def _client_ip(request) -> str | None:
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd[:45]
    ip = request.META.get("REMOTE_ADDR")
    return ip[:45] if ip else None


def _user_agent(request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:1024] if ua else None


def _audit(
    link_id,
    action: str,
    *,
    ip: str | None = None,
    ua: str | None = None,
    reason: str | None = None,
) -> None:
    ShareLinkAudit.objects.create(link_id=link_id, action=action, ip=ip, user_agent=ua, reason=reason)


def serialize_link(link: ShareableLink) -> dict:
    """LinkOut — список/detail-вью, НИКОГДА не несёт token/url."""
    return {
        "id": str(link.id),
        "label": link.label,
        "viewer_label": link.viewer_label,
        "watermark_text": link.watermark_text,
        "max_level": link.max_level,
        "default_language": link.default_language,
        "link_type": link.link_type,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "opened_at": link.opened_at.isoformat() if link.opened_at else None,
        "used_at": link.used_at.isoformat() if link.used_at else None,
        "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
        "is_active": link.is_active,
        "created_at": link.created_at.isoformat(),
        "target_type": link.target_type,
        "target_employee_id": link.target_employee_id,
    }


def serialize_audit_entry(entry: ShareLinkAudit) -> dict:
    return {
        "id": entry.id,
        "action": entry.action,
        "occurred_at": entry.occurred_at.isoformat(),
        "ip": entry.ip,
        "user_agent": entry.user_agent,
        "reason": entry.reason,
    }


# ── Аутентифицированные операции ────────────────────────────────────────────

def create_link(user_id: int, data: dict) -> CreatedLink:
    raw = _generate_raw_token()
    target_type = data.get("target_type") or "org"
    target_employee_id = data.get("target_employee_id")
    if target_type == "employee" and not target_employee_id:
        raise TargetEmployeeRequired
    if target_type == "org":
        target_employee_id = None

    link = ShareableLink.objects.create(
        token=None,  # plaintext-колонка зарезервирована только под legacy-строки
        token_hash=_hash_token(raw),
        created_by_user_id=user_id,
        label=data.get("label"),
        viewer_label=data.get("viewer_label"),
        watermark_text=data.get("watermark_text"),
        max_level=data.get("max_level", 3),
        default_language=data.get("default_language") or "ru",
        visible_units=data.get("visible_units"),
        link_type=data.get("link_type", "one_time"),
        expires_at=data.get("expires_at"),
        target_type=target_type,
        target_employee_id=target_employee_id,
        is_active=True,
    )
    _audit(link.id, "created", reason=f"user_id={user_id}")
    return CreatedLink(link=link, raw_token=raw)


def list_links(user_id: int) -> list[ShareableLink]:
    return list(ShareableLink.objects.filter(created_by_user_id=user_id).order_by("-created_at"))


def get_link(link_id, user_id: int) -> ShareableLink:
    link = ShareableLink.objects.filter(id=link_id, created_by_user_id=user_id).first()
    if link is None:
        raise LinkNotFound
    return link


def revoke_link(link_id, user_id: int) -> None:
    link = get_link(link_id, user_id)
    if not link.is_active:
        return  # идемпотентно; уже отозвана или использована
    now = timezone.now()
    link.is_active = False
    link.revoked_at = now
    link.save(update_fields=["is_active", "revoked_at"])
    _audit(link.id, "revoked", reason=f"user_id={user_id}")


def list_audit(link_id, user_id: int, limit: int = 200) -> list[ShareLinkAudit]:
    # Авторизация: убеждаемся, что ссылка принадлежит вызывающему, ДО показа аудита.
    get_link(link_id, user_id)
    return list(ShareLinkAudit.objects.filter(link_id=link_id).order_by("-occurred_at")[:limit])


# ── Публичное потребление ────────────────────────────────────────────────

def _resolve_and_validate(request, raw_token: str, *, expected_target: str | None = None):
    """Общий пайплайн валидации: блокирует строку, прогоняет все deny-checks,
    помечает opened/used, возвращает ``(link, ip, ua)``.

    Поднимает соответствующее исключение при каждой причине отказа
    (revoked/used/expired/wrong target type). Мутация состояния (флип
    ``is_active`` при истечении/успешном one-time открытии + запись аудита)
    коммитится ДАЖЕ когда запрос в итоге отвечает ошибкой — буквальный порт
    построчных ``await self.session.commit()`` исходника перед каждым
    ``raise`` в deny-ветках: ошибка распространяется ПОСЛЕ выхода из
    ``transaction.atomic()``, а не изнутри него.
    """
    token_hash = _hash_token(raw_token)
    ip = _client_ip(request)
    ua = _user_agent(request)

    with transaction.atomic():
        link = ShareableLink.objects.select_for_update().filter(token_hash=token_hash).first()

        if link is None:
            error: Exception | None = LinkNotFound()
        else:
            now = timezone.now()
            error = None

            if link.revoked_at is not None:
                _audit(link.id, "denied_revoked", ip=ip, ua=ua)
                error = LinkRevoked()
            elif link.link_type == "one_time" and link.used_at is not None:
                _audit(link.id, "denied_used", ip=ip, ua=ua)
                error = LinkAlreadyUsed()
            elif link.expires_at and link.expires_at < now:
                link.is_active = False
                link.save(update_fields=["is_active"])
                _audit(link.id, "denied_expired", ip=ip, ua=ua)
                error = LinkExpired()
            elif not link.is_active:
                # Belt-and-braces для legacy-строк, где is_active=False без
                # маркера revoked_at/used_at — считаем отозванной.
                _audit(link.id, "denied_revoked", ip=ip, ua=ua, reason="legacy_inactive")
                error = LinkInactive()
            elif expected_target is not None and (link.target_type or "org") != expected_target:
                # /public/org/{token} — только для org-ссылок; employee-ссылка,
                # потреблённая здесь, раскрыла бы всю компанию. Прячем как 404,
                # чтобы не дать зондам угадать тип цели по разнице кодов ответа.
                _audit(link.id, "denied_revoked", ip=ip, ua=ua, reason="wrong_target_type")
                error = LinkNotFound()
            else:
                link.opened_at = now
                link.opened_by_ip = ip
                if link.link_type == "one_time":
                    link.used_at = now
                    link.is_active = False
                link.save(update_fields=["opened_at", "opened_by_ip", "used_at", "is_active"])
                _audit(link.id, "open", ip=ip, ua=ua)

    if error is not None:
        raise error
    return link, ip, ua


def _strip_public_pii(tree: dict) -> dict:
    cleaned = copy.deepcopy(tree)
    for node in cleaned.get("nodes") or []:
        meta = node.get("meta") or {}
        for f in PII_FIELDS:
            meta.pop(f, None)
        # Публичные ссылки намеренно раскрывают верхнеуровневые holder_email/
        # holder_phone для видимых карточек. Вложенные holders остаются
        # summary-only, чтобы не раскрывать контакты, которые UI не отрисовывает.
        if isinstance(meta.get("holders"), list):
            meta["holders"] = [
                {k: v for k, v in h.items() if k not in NESTED_HOLDER_PII_FIELDS}
                for h in meta["holders"]
                if isinstance(h, dict)
            ]
        node["meta"] = meta
    # relation_id адресует строку ReportingRelation/EmployeeReportingOverride
    # через /org/relations, /org/employee-relations — ручки правки, которых
    # у анонимного зрителя нет и быть не может (см. ручную правку
    # оргструктуры). Belt-and-braces поверх auth="jwt" на тех ручках: сам
    # id безвреден без доступа к API, но у этого файла принцип — резать на
    # уровне схемы, а не полагаться на то, что снаружи никто не спросит.
    # origin остаётся — он не адресует ничего, просто "явно"/"выведено", и
    # даёт анонимному зрителю тот же честный пунктир на угаданных связях.
    for edge in cleaned.get("edges") or []:
        edge.pop("relation_id", None)
    return cleaned


def _build_watermark(link: ShareableLink, *, ip: str | None, opened_at) -> dict:
    """Фронт отрисовывает это как CSS-оверлей поверх диаграммы."""
    ip_tail = ""
    if ip:
        parts = ip.split(".")
        ip_tail = parts[-1] if len(parts) == 4 else ip[-4:]
    return {
        "viewer_label": link.viewer_label,
        "text": link.watermark_text,
        "opened_at": opened_at.isoformat() if opened_at else None,
        "ip_tail": ip_tail,
    }


def consume_link(request, raw_token: str) -> dict:
    """Валидирует raw_token и возвращает очищенное оргдерево.

    Для ``one_time``-ссылок: атомарно ставит ``opened_at``+``used_at`` и
    флипает ``is_active`` в ``False`` под блокировкой строки — конкурентное
    открытие не может успеть дважды.
    """
    link, ip, _ua = _resolve_and_validate(request, raw_token, expected_target="org")

    tree = org_service.get_org_tree(root_id=None, depth=20, mode="positions")

    # 1. visible_units (allow-list отделов)
    if link.visible_units:
        allowed = {str(u) for u in link.visible_units}
        tree["nodes"] = [
            n for n in tree["nodes"]
            if n["type"] != "department" or str((n.get("meta") or {}).get("id", "")) in allowed
        ]

    # 2. max_level (потолок уровня должности). Фантомные/department-узлы имеют
    # level=None и остаются видимыми. Рёбра, ссылающиеся на удалённые узлы,
    # обрезаются, чтобы сырой публичный JSON не обходил ограничение ссылки.
    if link.max_level:
        kept = [
            n for n in tree["nodes"]
            if n.get("level") is None or n["level"] <= link.max_level
        ]
        visible_ids = {n["id"] for n in kept}
        tree["nodes"] = kept
        tree["edges"] = [
            e for e in tree["edges"]
            if e["source"] in visible_ids and e["target"] in visible_ids
        ]

    # 3. Зачистка чувствительных данных — belt-and-braces поверх
    #    schema-уровневого фильтра, который уже исключил эти поля.
    tree = _strip_public_pii(tree)

    translations: dict = {}
    en_tree = org_service.build_translated_org_tree(tree, "en")
    if en_tree is not None:
        translations["en"] = {"tree": _strip_public_pii(en_tree)}

    watermark = _build_watermark(link, ip=ip, opened_at=link.opened_at)

    return {
        "label": link.label,
        "max_level": link.max_level,
        "default_language": link.default_language,
        "generated_at": link.created_at.isoformat() if link.created_at else None,
        "watermark": watermark,
        "tree": tree,
        "translations": translations,
    }


def consume_employee_link(request, raw_token: str) -> dict:
    """Валидирует raw_token и возвращает очищенную карточку сотрудника.

    Зеркалит ``consume_link``, но для ``target_type='employee'``. Зачистка
    PII делается внутри ``EmployeeCardService.build_card(mode="public")`` —
    та же логика в одном месте.
    """
    link, ip, _ua = _resolve_and_validate(request, raw_token, expected_target="employee")
    if not link.target_employee_id:
        raise LinkNotFound

    try:
        card = card_svc.build_card(link.target_employee_id, mode="public")
    except emp_svc.EmployeeNotFound as exc:
        raise EmployeeLinkGone from exc

    watermark = _build_watermark(link, ip=ip, opened_at=link.opened_at)

    return {
        "label": link.label,
        "default_language": link.default_language,
        "generated_at": link.created_at.isoformat() if link.created_at else None,
        "watermark": watermark,
        "card": card,
    }
