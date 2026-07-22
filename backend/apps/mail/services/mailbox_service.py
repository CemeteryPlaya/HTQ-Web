"""Mailbox provisioning service — порт
``services/email/app/services/mailbox_service.py`` (mailboxes-под-задача,
mail-mailboxes-brief.md).

Паттерн исходника:
  1. HTTP-обработчик зовёт сюда.
  2. Сервис синхронно обновляет свою локальную строку (админ видит "active"
     сразу) и ставит в очередь Dramatiq-актора для медленного внешнего
     Mailcow-вызова.
  3. Актор реально бьёт в Mailcow API и переводит строку в
     active/archived/deleted/error с ретраями на транзиентные ошибки.

Р2 этого Django-порта (тот же принцип, что ``account_service.py::
trigger_sync`` и ``email_service.py::send_email`` в mail-messages):
``services/email/app/workers/mailbox_actors.py`` НЕ портируется — это
отдельная под-задача workers (Celery-эквивалент dramatiq, см. CLAUDE.md).
Поэтому шаги 2 выполняются буквально (та же локальная строка/статус/
переходы, те же коды ошибок), а шаг 3 (реальный HTTP-вызов в Mailcow) здесь
НЕ ставится в очередь — ``apps/mail/services/mailcow_client.py`` перенесён и
unit-тестируется, но вызывается напрямую отсюда единственный раз НИКОГДА
(actor'ы — единственный вызывающий в исходнике; aliases/forwarding в
``views.py`` зовут ``MailcowClient`` напрямую, синхронно, как и исходный
роутер). Наблюдаемый контракт ЭТОГО модуля (локальная строка + статусы +
коды ошибок) идентичен исходнику ДО постановки в очередь.

Username autogen rule (i.ivanov from "Иван Иванов"):
  - Cyrillic → Latin via small translit table (mirrors hr/department_service)
  - first letter of first_name + "." + lowercased last_name, alnum-only
  - On conflict, append numeric suffix: i.ivanov, i.ivanov2, i.ivanov3, …
"""
from __future__ import annotations

import re
import secrets
import string

from django.conf import settings
from django.utils import timezone as django_timezone

from apps.mail.models import ProvisionedMailbox


# ── Domain exceptions (порт HTTPException(...) исходника) ──────────────────

class MailboxNotFound(Exception):
    """404 — Mailbox not found."""


class MailboxDomainNotConfigured(Exception):
    """500 — MAILCOW_DOMAIN not configured."""


class MailboxUserConflict(Exception):
    """409 — user_id уже привязан к другому (не удалённому) ящику."""

    def __init__(self, user_id: int, address: str) -> None:
        self.detail = f"User {user_id} already has mailbox {address}"
        super().__init__(self.detail)


class InvalidLocalPart(Exception):
    """400 — local_part после санитайза оказался пустым."""


class MailboxAlreadyDeleted(Exception):
    """409 — update() на уже удалённой строке."""


class MailboxNotActive(Exception):
    """409 — reset_password() на не-active строке."""


class CannotArchive(Exception):
    """409 — archive() из статуса, отличного от active/error."""

    def __init__(self, status: str) -> None:
        self.detail = f"Cannot archive mailbox in status={status}"
        super().__init__(self.detail)


class CannotRestore(Exception):
    """409 — restore() не из archived."""


class CannotDelete(Exception):
    """409 — delete() (stage 2) не из archived."""


# ── Helpers (буквальный порт) ────────────────────────────────────────────

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(s: str) -> str:
    return "".join(_TRANSLIT.get(c, c) for c in s.lower())


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _translit(s))


def autogen_local_part(first_name: str, last_name: str) -> str:
    """`Иван Иванов` → `i.ivanov`; `Ivan` → `ivan`; both empty → `user`."""
    fn = _slug(first_name)
    ln = _slug(last_name)
    if fn and ln:
        return f"{fn[0]}.{ln}"
    return fn or ln or "user"


def generate_password(length: int = 16) -> str:
    """Strong random password — letters, digits, a few symbols.

    Avoids characters that Mailcow's PHP layer or shells may treat oddly
    (`'\"\\`)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_-+="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _next_unique_local_part(base: str, domain: str) -> str:
    """Return base, base2, base3, … — first one whose address is unused."""
    candidate = base
    n = 2
    while True:
        address = f"{candidate}@{domain}"
        if not ProvisionedMailbox.objects.filter(address=address).exists():
            return candidate
        candidate = f"{base}{n}"
        n += 1


def serialize(mb: ProvisionedMailbox) -> dict:
    """Порт schemas/mailbox.py::MailboxOut."""
    return {
        "id": mb.id,
        "user_id": mb.user_id,
        "local_part": mb.local_part,
        "domain": mb.domain,
        "address": mb.address,
        "status": mb.status,
        "quota_mb": mb.quota_mb,
        "display_name": mb.display_name,
        "last_error": mb.last_error,
        "created_at": mb.created_at.isoformat(),
        "updated_at": mb.updated_at.isoformat(),
        "archived_at": mb.archived_at.isoformat() if mb.archived_at else None,
        "deleted_at": mb.deleted_at.isoformat() if mb.deleted_at else None,
    }


# ── Reads ────────────────────────────────────────────────────────────────

def list_mailboxes(*, include_deleted: bool = False) -> list[ProvisionedMailbox]:
    qs = ProvisionedMailbox.objects.order_by("-created_at")
    if not include_deleted:
        qs = qs.exclude(status="deleted")
    return list(qs)


def get_by_id(mailbox_id: int) -> ProvisionedMailbox:
    mb = ProvisionedMailbox.objects.filter(id=mailbox_id).first()
    if mb is None:
        raise MailboxNotFound
    return mb


def get_by_user_id(user_id: int) -> ProvisionedMailbox | None:
    return ProvisionedMailbox.objects.filter(user_id=user_id).first()


# ── Writes ───────────────────────────────────────────────────────────────

def create(payload) -> tuple[ProvisionedMailbox, str | None]:
    """Create a mailbox row (порт исходника МИНУС постановка в очередь —
    см. модуль docstring, Р2).

    Returns (row, generated_password). `generated_password` is None when
    the admin provided one — we never echo back what we received.
    """
    domain = getattr(settings, "MAILCOW_DOMAIN", "")
    if not domain:
        raise MailboxDomainNotConfigured

    # Unique-by-user_id: don't let a user end up with two mailboxes.
    if payload.user_id is not None:
        existing = get_by_user_id(payload.user_id)
        if existing and existing.status != "deleted":
            raise MailboxUserConflict(payload.user_id, existing.address)

    local = (payload.local_part or "").strip().lower()
    if not local:
        local = autogen_local_part(payload.first_name, payload.last_name)
    # Sanitize whatever was passed — Mailcow accepts a-z0-9._-
    local = re.sub(r"[^a-z0-9._-]+", "", local)
    if not local:
        raise InvalidLocalPart
    local = _next_unique_local_part(local, domain)

    password = payload.password or generate_password()
    generated = None if payload.password else password

    quota = payload.quota_mb or getattr(settings, "MAILCOW_DEFAULT_QUOTA_MB", 1024)
    full_name = payload.full_name or f"{payload.first_name} {payload.last_name}".strip()
    address = f"{local}@{domain}"

    mb = ProvisionedMailbox.objects.create(
        user_id=payload.user_id,
        local_part=local,
        domain=domain,
        address=address,
        status="active",
        quota_mb=quota,
        display_name=full_name or None,
    )
    return mb, generated


def update(mailbox_id: int, payload) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status == "deleted":
        raise MailboxAlreadyDeleted
    changed_fields = []
    if payload.full_name is not None:
        mb.display_name = payload.full_name
        changed_fields.append("display_name")
    if payload.quota_mb is not None and payload.quota_mb != mb.quota_mb:
        mb.quota_mb = payload.quota_mb
        changed_fields.append("quota_mb")
    if changed_fields:
        mb.save(update_fields=[*changed_fields, "updated_at"])
    return mb


def reset_password(mailbox_id: int, payload) -> tuple[ProvisionedMailbox, str | None]:
    mb = get_by_id(mailbox_id)
    if mb.status != "active":
        raise MailboxNotActive
    password = payload.new_password or generate_password()
    generated = None if payload.new_password else password
    return mb, generated


def archive(mailbox_id: int) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status == "archived":
        return mb
    if mb.status not in ("active", "error"):
        raise CannotArchive(mb.status)
    mb.status = "archived"
    mb.archived_at = django_timezone.now()
    mb.save(update_fields=["status", "archived_at", "updated_at"])
    return mb


def restore(mailbox_id: int) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotRestore
    mb.status = "active"
    mb.archived_at = None
    mb.save(update_fields=["status", "archived_at", "updated_at"])
    return mb


def delete(mailbox_id: int) -> None:
    """Stage 2 of the two-step delete — only allowed when archived.

    Marks our row as `deleted` (kept as audit trail); порт исходника МИНУС
    постановка реального Mailcow DELETE в очередь (Р2, см. модуль docstring).
    """
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotDelete
    mb.status = "deleted"
    mb.deleted_at = django_timezone.now()
    mb.save(update_fields=["status", "deleted_at", "updated_at"])
