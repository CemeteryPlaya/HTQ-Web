"""Common shape for all provider sync drivers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import EmailAccount


@dataclass
class SyncResult:
    """Aggregate counters returned from any sync run."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    attachments_saved: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> "SyncResult":
        return SyncResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            deleted=self.deleted + other.deleted,
            attachments_saved=self.attachments_saved + other.attachments_saved,
            errors=self.errors + other.errors,
        )


@runtime_checkable
class SyncDriver(Protocol):
    """Provider-specific mailbox sync.

    Implementations must be idempotent — both ``initial_backfill`` and
    ``incremental`` UPSERT into ``email_messages`` keyed on
    ``(account_id, message_id)`` so re-running a sync does not create
    duplicates.
    """

    provider: str

    async def initial_backfill(
        self,
        account: EmailAccount,
        session: AsyncSession,
        *,
        max_messages: int,
    ) -> SyncResult: ...

    async def incremental(
        self,
        account: EmailAccount,
        session: AsyncSession,
        *,
        hint: dict | None = None,
    ) -> SyncResult: ...

    async def register_push(
        self, account: EmailAccount, session: AsyncSession
    ) -> None:
        """Register a webhook / watch / IDLE selector entry. Phase 5."""

    async def renew_push(
        self, account: EmailAccount, session: AsyncSession
    ) -> None:
        """Refresh expiring subscription. Phase 5."""

    async def unregister_push(
        self, account: EmailAccount, session: AsyncSession
    ) -> None:
        """Tear down on disconnect. Phase 5."""
