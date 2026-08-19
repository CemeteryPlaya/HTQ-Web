"""Pydantic-схемы тел запросов домена mail — порт
``services/email/app/schemas/email.py`` (только тела запросов; формы ответов
собираются сериализаторами в ``apps/mail/services/*``, тот же принцип, что и
``apps/hr/schemas.py``). Дополнено mailboxes-под-задачей (mail-mailboxes-
brief.md) — порт ``services/email/app/schemas/mailbox.py`` (тоже только
тела запросов; ``MailboxOut``/``AliasOut`` собираются
``apps/mail/services/mailbox_service.py::serialize``).
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EmailSendRequest(BaseModel):
    """Порт schemas/email.py::EmailSendRequest."""

    account_id: int
    to_recipients: list[dict]  # [{"email": "a@b.com", "name": "A"}]
    cc_recipients: list[dict] = []
    bcc_recipients: list[dict] = []
    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    # Странность исходника (см. apps/mail/services/email_service.py::
    # send_email docstring): emails.py::send_email принимает это поле в
    # схеме запроса, но НИКОГДА его не читает в теле функции — вложения
    # на отправку не подключены (mime.py::build_mime получает
    # attachments=() по умолчанию). Перенесено как есть.
    attachment_ids: list[uuid.UUID] = []


class DraftIn(BaseModel):
    """Порт emails.py::DraftIn (module-level ``_Base`` в исходнике)."""

    subject: str = ""
    body: str = ""


# ── mailboxes (mail-mailboxes-brief.md, порт schemas/mailbox.py) ──────────

_EMAIL_RE = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class MailboxCreateRequest(BaseModel):
    """Body for `POST /api/email/v1/mailboxes/`."""

    # When `local_part` is empty, the server auto-generates from first/last
    # name (transliterated, e.g. "Иван Иванов" → "i.ivanov"). With a
    # conflict it appends 2, 3, … until unique.
    local_part: str = Field(default="", max_length=64, description="Part before @; '' = autogen from name")
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)
    full_name: str = Field(default="", max_length=255, description="Display name in mailbox metadata")
    # When `password` is empty, the server generates a strong random one and
    # returns it once in the response (admin must capture it).
    password: str = Field(default="", description="Plain text; '' = autogen and return once")
    quota_mb: int = Field(default=0, ge=0, description="0 = use MAILCOW_DEFAULT_QUOTA_MB")
    user_id: int | None = Field(default=None, description="Link to platform user; one mailbox per user_id")
    must_change_password: bool = Field(default=True)
    # Сверка перед созданием: найденный ящик подключается к пользователю
    # вместо заведения дубля. Выключается, когда админу нужен именно НОВЫЙ
    # адрес (второй однофамилец), а не тот, что уже есть.
    attach_if_exists: bool = Field(
        default=True,
        description="Attach an already existing mailbox instead of creating a duplicate",
    )


class MailboxLookupResponse(BaseModel):
    """Ответ `GET /api/email/v1/mailboxes/lookup/` — вердикт сверки адреса.

    Форма создания читает его, чтобы сказать админу, что произойдёт по
    кнопке, ДО того как он её нажмёт. Порт dataclass
    ``services/lookup_service.py::MailboxLookup``.
    """

    address: str
    exists: bool = False
    source: str = Field(default="none", description="none | local | remote | both")
    checked_remote: bool = False
    remote_detail: str | None = None
    mailbox: dict | None = None
    owner_user_id: int | None = None
    owner_conflict: bool = False
    can_attach: bool = False
    needs_password: bool = False
    detail: str = ""


class MailboxUpdateRequest(BaseModel):
    """Body for `PATCH /api/email/v1/mailboxes/{id}/`."""

    full_name: str | None = Field(default=None, max_length=255)
    quota_mb: int | None = Field(default=None, ge=0)


class MailboxResetPasswordRequest(BaseModel):
    new_password: str = Field(default="", description="'' = autogen and return once")
    force_change: bool = Field(default=True)


class AliasCreateRequest(BaseModel):
    address: str = Field(..., max_length=255)
    goto: str = Field(..., description="Comma-separated list of destination addresses")
    active: bool = True

    @field_validator("address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v


class ReconcileRequest(BaseModel):
    """Body for `POST /api/email/v1/mailboxes/reconcile/`.

    ``apply=False`` (дефолт) — тот же отчёт, что и на GET: посчитать
    расхождения, ничего не трогая. ``direction`` определяет, кто источник
    правды при ``apply=True`` (см. reconcile_service.reconcile).
    """

    apply: bool = False
    direction: str = Field(default="report", description="report | pull | push | both")

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, v: str) -> str:
        allowed = ("report", "pull", "push", "both")
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}")
        return v


class ImapAccountConnectRequest(BaseModel):
    """Body for `POST /api/email/v1/accounts/connect-imap/`.

    Пользователь подключает СВОЙ почтовый аккаунт на произвольном сервере —
    поля те же, что просит любой почтовый клиент. Значения по умолчанию
    (993/SSL для IMAP, 587/STARTTLS для SMTP) покрывают большинство серверов;
    предзаполнить форму помогает `GET .../connect-imap/?address=...`.
    """

    address: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1)
    # Логин обычно равен адресу, но не везде — оставляем возможность задать.
    username: str = Field(default="", max_length=255)
    display_name: str = Field(default="", max_length=255)

    imap_host: str = Field(..., min_length=1, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_ssl: bool = True
    imap_starttls: bool = False

    # "" = тот же хост, что IMAP.
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_ssl: bool = False
    smtp_starttls: bool = True

    @field_validator("address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v


class ImapAccountPasswordRequest(BaseModel):
    """Body for `POST /api/email/v1/accounts/{id}/imap-password/`."""

    password: str = Field(..., min_length=1)


class MailSettingsRequest(BaseModel):
    """Body for `PUT /api/email/v1/mailboxes/settings/`.

    Все поля необязательны и обрабатываются по ``exclude_unset``: форма шлёт
    только то, что реально меняет. Пустая строка / ``null`` в текстовом поле
    означает «убрать перекрытие и вернуться к переменной окружения» — см.
    ``services/mail_config.py`` про правило слияния.
    """

    provisioner: Optional[str] = Field(default=None, description="'' | auto | mailcow | imap | none")
    domain: Optional[str] = Field(default=None, max_length=255)

    imap_host: Optional[str] = Field(default=None, max_length=255)
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    imap_ssl: Optional[bool] = None
    imap_starttls: Optional[bool] = None
    imap_tls_server_hostname: Optional[str] = Field(default=None, max_length=255)

    smtp_host: Optional[str] = Field(default=None, max_length=255)
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_ssl: Optional[bool] = None
    smtp_starttls: Optional[bool] = None

    mailcow_api_url: Optional[str] = Field(default=None, max_length=500)
    # "" = не менять (форма не знает текущего значения, секрет наружу не
    # отдаётся); null = стереть и вернуться к MAILCOW_API_KEY из окружения.
    mailcow_api_key: Optional[str] = None

    sync_folders: Optional[list[str]] = None
    sync_push_flags: Optional[bool] = None
    allow_self_service: Optional[bool] = None
    local_part_pattern: Optional[str] = Field(
        default=None, description="'' | first.last | f.last | firstlast | first_last | flast | last.first | first",
    )

    @field_validator("local_part_pattern")
    @classmethod
    def _validate_local_part_pattern(cls, v: str | None) -> str | None:
        from apps.mail.services.mailbox_service import LOCAL_PART_PATTERNS

        if v not in (None, "", *LOCAL_PART_PATTERNS):
            raise ValueError(
                "local_part_pattern must be one of: " + ", ".join(LOCAL_PART_PATTERNS)
            )
        return v

    @field_validator("provisioner")
    @classmethod
    def _validate_provisioner(cls, v: str | None) -> str | None:
        allowed = ("", "auto", "mailcow", "imap", "none")
        if v is not None and v not in allowed:
            raise ValueError(f"provisioner must be one of {allowed}")
        return v


class MailConnectionTestRequest(BaseModel):
    """Body for `POST /api/email/v1/mailboxes/settings/test/`.

    Без ``mailbox`` проверяются только настройки и доступность портов — этого
    достаточно для отладки туннеля и не требует ни одного секрета.
    ``send_to`` отправляет НАСТОЯЩЕЕ письмо, поэтому задаётся явно.
    """

    mailbox: str = ""
    password: str = ""
    send_to: str = ""
    timeout: int = Field(default=10, ge=1, le=60)


class MailboxConnectRequest(BaseModel):
    """Body for `POST /api/email/v1/accounts/connect-corporate/` —
    самоподключение ящика сотрудником."""

    address: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1)

    @field_validator("address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v


class ForwardingSetRequest(BaseModel):
    forward_to: str = Field(..., max_length=255)
    keep_local_copy: bool = True

    @field_validator("forward_to")
    @classmethod
    def _validate_forward_to(cls, v: str) -> str:
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v
