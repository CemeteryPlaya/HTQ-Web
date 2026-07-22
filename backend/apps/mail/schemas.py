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


class ForwardingSetRequest(BaseModel):
    forward_to: str = Field(..., max_length=255)
    keep_local_copy: bool = True

    @field_validator("forward_to")
    @classmethod
    def _validate_forward_to(cls, v: str) -> str:
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v
