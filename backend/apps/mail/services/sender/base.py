"""Common contract every provider sender implements — буквальный порт
``services/email/app/services/sender/base.py``.

``Sender`` Protocol исходника типизирован под ``async def send(account,
message, session)`` (SQLAlchemy AsyncSession) — здесь синхронно и без
``session``: Django ORM-объекты уже "живые" (не нужно явно передавать сессию
для сохранения обновлённого токена — см. ``sync/gmail.py::ensure_fresh_token``,
которая сохраняет через ``.save()`` сама)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from apps.mail.models import EmailAccount, EmailMessage


@dataclass
class SendResult:
    """Outcome of a single delivery attempt."""

    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@runtime_checkable
class Sender(Protocol):
    """Strategy interface — one impl per provider."""

    provider: str

    def send(self, account: EmailAccount, message: EmailMessage) -> SendResult: ...
