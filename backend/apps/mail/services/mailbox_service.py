"""Mailbox provisioning service — порт
``services/email/app/services/mailbox_service.py`` (mailboxes-под-задача,
mail-mailboxes-brief.md).

Раньше этот модуль работал ТОЛЬКО с локальной строкой: реальный вызов на
почтовый сервер был отложен («Р2»: dramatiq-актор ``mailbox_actors.py`` не
портировался). Из-за этого ящик, «созданный» на сайте, на почтовом сервере
не появлялся. Теперь каждая операция после локального перехода дёргает
``services/provisioning`` — подключаемый слой, который знает, что именно
умеет конкретный почтовый сервер (Mailcow REST API / голый IMAP / ничего).

Как распределены ответственности при ошибке сервера:

* **Локальный переход выполняется всегда** — ровно как раньше, поэтому все
  существующие коды ответов (404/409/…) сохранены дословно.
* **Отказ сервера не откатывает строку молча**: он попадает в
  ``ProvisionedMailbox.last_error``, а для create/reset-password ещё и
  переводит строку в ``status="error"`` — админка ящиков показывает это
  прямо в таблице (колонка адреса рисует ``last_error`` красным).
* В неконфигурированном окружении провижинер — ``NoopProvisioner``, то есть
  поведение бит-в-бит прежнее (обратная совместимость).

Username autogen rule (i.ivanov from "Иван Иванов"):
  - Cyrillic → Latin via small translit table (mirrors hr/department_service)
  - first letter of first_name + "." + lowercased last_name, alnum-only
  - On conflict, append numeric suffix: i.ivanov, i.ivanov2, i.ivanov3, …
    (только когда сервер умеет заводить ящики сам; для IMAP-режима адрес
    обязан совпасть с уже существующим на сервере, поэтому там занятый
    адрес — это 409, а не тихое переименование)
"""
from __future__ import annotations

import logging
import re
import secrets
import string

from django.conf import settings
from django.utils import timezone as django_timezone

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import mail_config
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning import ProvisioningError, get_provisioner

log = logging.getLogger(__name__)


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


class MailboxAddressTaken(Exception):
    """409 — адрес уже занят локальной строкой.

    Возникает только в режиме, где сервер не заводит ящики сам (IMAP): там
    адрес нельзя тихо переименовать в ``i.ivanov2``, он должен совпадать с
    реальным ящиком на сервере.
    """

    def __init__(self, address: str) -> None:
        self.detail = f"Mailbox {address} already exists"
        super().__init__(self.detail)


class RemoteProvisioningFailed(Exception):
    """502 — почтовый сервер отказал.

    Локальная строка при этом уже создана/обновлена и помечена
    ``status="error"`` + ``last_error`` — админ видит её в списке и может
    повторить операцию, а не остаётся с «ничего не произошло».
    """

    def __init__(self, detail: str, mailbox: ProvisionedMailbox | None = None) -> None:
        self.detail = detail
        self.mailbox = mailbox
        super().__init__(detail)


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


#: как собрать адрес из транслитерированных имени и фамилии
LOCAL_PART_PATTERNS = {
    "first.last": lambda fn, ln: f"{fn}.{ln}",     # sanzhar.inamzhanov
    "f.last": lambda fn, ln: f"{fn[0]}.{ln}",      # s.inamzhanov (историч. дефолт)
    "firstlast": lambda fn, ln: f"{fn}{ln}",       # sanzharinamzhanov
    "first_last": lambda fn, ln: f"{fn}_{ln}",     # sanzhar_inamzhanov
    "flast": lambda fn, ln: f"{fn[0]}{ln}",        # sinamzhanov
    "last.first": lambda fn, ln: f"{ln}.{fn}",     # inamzhanov.sanzhar
    "first": lambda fn, ln: fn,                    # sanzhar
}


def autogen_local_part(first_name: str, last_name: str, pattern: str | None = None) -> str:
    """`Санжар Инамжанов` → `sanzhar.inamzhanov` (шаблон ``first.last``).

    Соглашение об именовании у каждой компании своё, поэтому шаблон —
    настройка (``MAILBOX_LOCAL_PART_PATTERN`` либо поле «Шаблон адреса» в
    интерфейсе), а не константа. Промах здесь особенно дорог в IMAP-режиме:
    адрес обязан совпасть с реальным ящиком на сервере, иначе платформа
    сгенерирует несуществующий и создание просто не пройдёт.

    Дефолт кода — исторический ``f.last`` (``i.ivanov``): менять его глобально
    нельзя, не сломав уже работающие инсталляции.

    Одно из имён пустое → берётся то, что есть (шаблон неприменим); оба
    пустые → ``user``.
    """
    fn = _slug(first_name)
    ln = _slug(last_name)
    if not (fn and ln):
        return fn or ln or "user"

    if pattern is None:
        pattern = mail_config.get_config().local_part_pattern
    build = LOCAL_PART_PATTERNS.get(pattern)
    if build is None:
        log.warning(
            "unknown_local_part_pattern %r — используется f.last; допустимые: %s",
            pattern, ", ".join(LOCAL_PART_PATTERNS),
        )
        build = LOCAL_PART_PATTERNS["f.last"]
    return build(fn, ln)


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

def store_password(mb: ProvisionedMailbox, password: str) -> None:
    """Сохранить пароль ящика зашифрованным (AES-256-GCM, crypto.py).

    Без этого не работают ни синхронизация писем, ни отправка: и
    ``sync/imap_sync.py``, и ``sender/*_smtp.py`` берут учётку именно отсюда.
    Раньше поле не заполнял никто, из-за чего корпоративная отправка всегда
    падала на «mailcow mailbox has no app-password».
    """
    if not password:
        return
    mb.encrypted_smtp_app_password = crypto_service.encrypt(password)
    mb.save(update_fields=["encrypted_smtp_app_password", "updated_at"])


def stored_password(address: str) -> str | None:
    """Расшифрованный пароль уже заведённого ящика (или None).

    Нужен проверке подключения: админ, проверяющий существующий ящик, не
    должен вводить пароль заново — платформа его уже хранит.
    """
    mb = ProvisionedMailbox.objects.filter(address=address).first()
    if mb is None or not mb.encrypted_smtp_app_password:
        return None
    try:
        return crypto_service.decrypt(mb.encrypted_smtp_app_password)
    except Exception as exc:  # noqa: BLE001 — вызывающий сообщит «нет пароля»
        log.warning("stored_password_decrypt_failed address=%s: %s", address, exc)
        return None


def mark_error(mb: ProvisionedMailbox, error: str, *, status: str | None = None) -> None:
    mb.last_error = error
    fields = ["last_error", "updated_at"]
    if status is not None and mb.status != status:
        mb.status = status
        fields.append("status")
    mb.save(update_fields=fields)


def _clear_error(mb: ProvisionedMailbox) -> None:
    if mb.last_error:
        mb.last_error = None
        mb.save(update_fields=["last_error", "updated_at"])


def create(payload) -> tuple[ProvisionedMailbox, str | None]:
    """Завести ящик: локальная строка + реальное создание на почтовом сервере.

    Returns (row, generated_password). `generated_password` is None when
    the admin provided one — we never echo back what we received.

    Если сервер отказал, строка остаётся в БД со ``status="error"`` и текстом
    ошибки, а наружу летит ``RemoteProvisioningFailed`` (502) — так админ
    видит и что именно сломалось, и на какой строке, и может повторить.
    """
    cfg = mail_config.get_config()
    domain = cfg.domain
    if not domain:
        raise MailboxDomainNotConfigured

    # Unique-by-user_id: don't let a user end up with two mailboxes.
    if payload.user_id is not None:
        existing = get_by_user_id(payload.user_id)
        if existing and existing.status != "deleted":
            raise MailboxUserConflict(payload.user_id, existing.address)

    provisioner = get_provisioner()

    local = (payload.local_part or "").strip().lower()
    if not local:
        local = autogen_local_part(payload.first_name, payload.last_name)
    # Sanitize whatever was passed — Mailcow accepts a-z0-9._-
    local = re.sub(r"[^a-z0-9._-]+", "", local)
    if not local:
        raise InvalidLocalPart
    if getattr(provisioner, "requires_existing_mailbox", False):
        # Адрес обязан совпасть с реальным ящиком на сервере — подставить
        # свободный ``i.ivanov2`` нельзя, это была бы заведомо нерабочая
        # привязка. Занятый адрес здесь честнее вернуть как конфликт.
        if ProvisionedMailbox.objects.filter(address=f"{local}@{domain}").exists():
            raise MailboxAddressTaken(f"{local}@{domain}")
    else:
        # Сервер заведёт ящик под любым адресом (или ящика на сервере нет
        # вовсе) — свободный адрес можно подобрать за админа, как и раньше.
        local = _next_unique_local_part(local, domain)

    password = payload.password or generate_password()
    generated = None if payload.password else password

    quota = payload.quota_mb or cfg.mailcow_default_quota_mb
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

    try:
        provisioner.create(
            local_part=local, domain=domain, address=address, password=password,
            full_name=full_name, quota_mb=quota,
        )
    except ProvisioningError as exc:
        mark_error(mb, str(exc), status="error")
        raise RemoteProvisioningFailed(str(exc), mb) from exc

    # Пароль пригодится синхронизации и отправке — храним зашифрованным.
    store_password(mb, password)
    _issue_app_password(provisioner, mb, password)
    ensure_account(mb)
    return mb, generated


def account_provider() -> str:
    """Какое значение писать в ``EmailAccount.provider`` для нового ящика.

    Для неподключённого сервера остаётся историческое ``mailcow`` — так
    строки, созданные до подключения корпоративной почты, и строки, созданные
    после, выглядят одинаково, и отправка для них резолвится тем же
    отправителем, что и раньше.
    """
    from apps.mail.services.provisioning import resolve_provisioner_name

    return "imap" if resolve_provisioner_name() == "imap" else "mailcow"


def ensure_account(mb: ProvisionedMailbox):
    """Завести (или переиспользовать) ``EmailAccount`` для выданного ящика.

    Без этой строки ящик существует, но в интерфейсе почты его не видно:
    и список аккаунтов, и синхронизация, и отправка ходят через
    ``EmailAccount``, а создавал корпоративные аккаунты до сих пор никто —
    ящик оставался «мёртвой» строкой в админке.

    Ящик без ``user_id`` (импортированный сверкой, общий ящик вроде
    ``info@``) аккаунта не получает: он никому не принадлежит, показывать его
    некому. Аккаунт появится, когда ящик привяжут к сотруднику.
    """
    from apps.mail.models import AccountType, EmailAccount

    if mb.user_id is None:
        return None

    account = EmailAccount.objects.filter(user_id=mb.user_id, address=mb.address).first()
    if account is not None:
        if account.mailbox_id != mb.id or not account.is_active:
            account.mailbox_id = mb.id
            account.is_active = True
            account.save(update_fields=["mailbox", "is_active", "updated_at"])
        return account

    is_first = not EmailAccount.objects.filter(user_id=mb.user_id).exists()
    return EmailAccount.objects.create(
        user_id=mb.user_id,
        type=AccountType.CORPORATE,
        provider=account_provider(),
        address=mb.address,
        display_name=mb.display_name,
        mailbox=mb,
        # Корпоративный ящик — разумный дефолт для compose, если других нет.
        is_default=is_first,
        is_active=True,
    )


def _issue_app_password(provisioner, mb: ProvisionedMailbox, fallback: str) -> None:
    """Отдельный app-password для IMAP/SMTP там, где сервер это умеет.

    Best-effort: ящик уже создан и рабочий — если сервер не дал app-password,
    синхронизация просто пойдёт под основным паролем, ронять создание из-за
    этого нельзя.
    """
    issue = getattr(provisioner, "issue_app_password", None)
    if issue is None:
        return
    app_password = generate_password(24)
    try:
        issue(address=mb.address, password=app_password)
    except Exception as exc:  # noqa: BLE001 — не критично для создания ящика
        log.warning("app_password_issue_failed address=%s: %s", mb.address, exc)
        return
    store_password(mb, app_password)


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
        try:
            get_provisioner().update(
                address=mb.address, full_name=payload.full_name, quota_mb=payload.quota_mb,
            )
        except ProvisioningError as exc:
            # Правка имени/квоты не стоит отказа всего запроса: локальное
            # значение сохранено, расхождение с сервером видно в last_error
            # и попадёт в сверку.
            mark_error(mb, str(exc))
        else:
            _clear_error(mb)
    return mb


def reset_password(mailbox_id: int, payload) -> tuple[ProvisionedMailbox, str | None]:
    mb = get_by_id(mailbox_id)
    if mb.status != "active":
        raise MailboxNotActive
    password = payload.new_password or generate_password()
    generated = None if payload.new_password else password

    try:
        get_provisioner().reset_password(
            address=mb.address, new_password=password,
            force_change=getattr(payload, "force_change", True),
        )
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
        raise RemoteProvisioningFailed(str(exc), mb) from exc

    store_password(mb, password)
    _clear_error(mb)
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

    # На сервере архивация = ящик выключен: почта на него больше не ходит,
    # но данные целы (окончательное удаление — вторым этапом, delete()).
    try:
        get_provisioner().set_active(address=mb.address, active=False)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
    return mb


def restore(mailbox_id: int) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotRestore
    mb.status = "active"
    mb.archived_at = None
    mb.save(update_fields=["status", "archived_at", "updated_at"])

    try:
        get_provisioner().set_active(address=mb.address, active=True)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
    else:
        _clear_error(mb)
    return mb


def delete(mailbox_id: int) -> None:
    """Stage 2 of the two-step delete — only allowed when archived.

    Локальная строка остаётся как аудит-след (``status="deleted"``), а ящик
    на почтовом сервере удаляется по-настоящему. Отказ сервера не отменяет
    локальное удаление (иначе строка зависла бы в archived навсегда) — он
    пишется в ``last_error`` и всплывёт в сверке.
    """
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotDelete
    mb.status = "deleted"
    mb.deleted_at = django_timezone.now()
    mb.save(update_fields=["status", "deleted_at", "updated_at"])

    try:
        get_provisioner().delete(address=mb.address)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
