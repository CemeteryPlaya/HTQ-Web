"""Pydantic-схемы тел запросов домена mail — порт
``services/email/app/schemas/email.py`` (только тела запросов; формы ответов
собираются сериализаторами в ``apps/mail/services/*``, тот же принцип, что и
``apps/hr/schemas.py``).
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel


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
