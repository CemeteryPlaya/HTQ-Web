"""Common contract every provider sender implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import EmailAccount
from app.models.email import EmailMessage


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

    async def send(
        self,
        account: EmailAccount,
        message: EmailMessage,
        session: AsyncSession,
    ) -> SendResult: ...
