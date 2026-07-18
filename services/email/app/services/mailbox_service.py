"""Mailbox provisioning service — orchestrates DB row + Mailcow + Dramatiq.

Pattern:
  1. The HTTP handler calls into this service.
  2. The service updates our local DB row synchronously (so the admin sees
     "pending" immediately) and enqueues a Dramatiq actor for the slow
     external Mailcow call.
  3. The actor performs the Mailcow API call and updates the DB row to
     active/archived/deleted/error with retries on transient failures.

Username autogen rule (i.ivanov from "Иван Иванов"):
  - Cyrillic → Latin via small translit table (mirrors hr/department_service)
  - first letter of first_name + "." + lowercased last_name, alnum-only
  - On conflict, append numeric suffix: i.ivanov, i.ivanov2, i.ivanov3, …
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.mailbox import ProvisionedMailbox
from app.schemas.mailbox import (
    MailboxCreateRequest,
    MailboxResetPasswordRequest,
    MailboxUpdateRequest,
)


log = structlog.get_logger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────

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


# ── Service ─────────────────────────────────────────────────────────────────


class MailboxService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _next_unique_local_part(self, base: str, domain: str) -> str:  # noqa: ARG002
        """Return base, base2, base3, … — first one whose address is unused."""
        candidate = base
        n = 2
        while True:
            address = f"{candidate}@{domain}"
            existing = await self.db.execute(
                select(ProvisionedMailbox).where(ProvisionedMailbox.address == address)
            )
            if not existing.scalar_one_or_none():
                return candidate
            candidate = f"{base}{n}"
            n += 1

    async def list_mailboxes(self, *, include_deleted: bool = False) -> list[ProvisionedMailbox]:
        stmt = select(ProvisionedMailbox).order_by(ProvisionedMailbox.created_at.desc())
        if not include_deleted:
            stmt = stmt.where(ProvisionedMailbox.status != "deleted")
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, mailbox_id: int) -> ProvisionedMailbox:
        result = await self.db.execute(select(ProvisionedMailbox).where(ProvisionedMailbox.id == mailbox_id))
        mb = result.scalar_one_or_none()
        if not mb:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        return mb

    async def get_by_user_id(self, user_id: int) -> ProvisionedMailbox | None:
        result = await self.db.execute(
            select(ProvisionedMailbox).where(ProvisionedMailbox.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, payload: MailboxCreateRequest) -> tuple[ProvisionedMailbox, str | None]:
        """Create a mailbox row + enqueue the Mailcow create.

        Returns (row, generated_password). `generated_password` is None when
        the admin provided one — we never echo back what we received.
        """
        if not settings.mailcow_domain:
            raise HTTPException(status_code=500, detail="MAILCOW_DOMAIN not configured")

        # Unique-by-user_id: don't let a user end up with two mailboxes.
        if payload.user_id is not None:
            existing = await self.get_by_user_id(payload.user_id)
            if existing and existing.status != "deleted":
                raise HTTPException(
                    status_code=409,
                    detail=f"User {payload.user_id} already has mailbox {existing.address}",
                )

        domain = settings.mailcow_domain
        local = (payload.local_part or "").strip().lower()
        if not local:
            local = autogen_local_part(payload.first_name, payload.last_name)
        # Sanitize whatever was passed — Mailcow accepts a-z0-9._-
        local = re.sub(r"[^a-z0-9._-]+", "", local)
        if not local:
            raise HTTPException(status_code=400, detail="Invalid local_part")
        local = await self._next_unique_local_part(local, domain)

        password = payload.password or generate_password()
        generated = None if payload.password else password

        quota = payload.quota_mb or settings.mailcow_default_quota_mb
        full_name = payload.full_name or f"{payload.first_name} {payload.last_name}".strip()
        address = f"{local}@{domain}"

        mb = ProvisionedMailbox(
            user_id=payload.user_id,
            local_part=local,
            domain=domain,
            address=address,
            status="active",
            quota_mb=quota,
            display_name=full_name or None,
        )
        self.db.add(mb)
        await self.db.commit()
        await self.db.refresh(mb)

        # Lazy import to avoid loading dramatiq broker during sqladmin init.
        from app.workers.mailbox_actors import provision_mailbox
        provision_mailbox.send(
            mailbox_id=mb.id,
            local_part=local,
            domain=domain,
            password=password,
            full_name=full_name,
            quota_mb=quota,
            force_change=payload.must_change_password,
        )
        log.info("mailbox_create_enqueued", mailbox_id=mb.id, address=address, user_id=mb.user_id)
        return mb, generated

    async def update(self, mailbox_id: int, payload: MailboxUpdateRequest) -> ProvisionedMailbox:
        mb = await self.get_by_id(mailbox_id)
        if mb.status in ("deleted",):
            raise HTTPException(status_code=409, detail="Mailbox already deleted")
        attr: dict[str, str] = {}
        if payload.full_name is not None:
            mb.display_name = payload.full_name
            attr["name"] = payload.full_name
        if payload.quota_mb is not None and payload.quota_mb != mb.quota_mb:
            mb.quota_mb = payload.quota_mb
            attr["quota"] = str(payload.quota_mb)
        await self.db.commit()
        await self.db.refresh(mb)

        if attr:
            from app.workers.mailbox_actors import update_mailbox
            update_mailbox.send(address=mb.address, attr=attr, mailbox_id=mb.id)
        return mb

    async def reset_password(
        self, mailbox_id: int, payload: MailboxResetPasswordRequest,
    ) -> tuple[ProvisionedMailbox, str | None]:
        mb = await self.get_by_id(mailbox_id)
        if mb.status != "active":
            raise HTTPException(status_code=409, detail="Mailbox is not active")
        password = payload.new_password or generate_password()
        generated = None if payload.new_password else password

        from app.workers.mailbox_actors import reset_mailbox_password
        reset_mailbox_password.send(
            address=mb.address,
            new_password=password,
            force_change=payload.force_change,
            mailbox_id=mb.id,
        )
        log.info("mailbox_reset_enqueued", mailbox_id=mb.id, address=mb.address)
        return mb, generated

    async def archive(self, mailbox_id: int) -> ProvisionedMailbox:
        mb = await self.get_by_id(mailbox_id)
        if mb.status == "archived":
            return mb
        if mb.status not in ("active", "error"):
            raise HTTPException(status_code=409, detail=f"Cannot archive mailbox in status={mb.status}")
        mb.status = "archived"
        mb.archived_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(mb)

        from app.workers.mailbox_actors import archive_mailbox
        archive_mailbox.send(address=mb.address, mailbox_id=mb.id)
        log.info("mailbox_archive_enqueued", mailbox_id=mb.id, address=mb.address)
        return mb

    async def restore(self, mailbox_id: int) -> ProvisionedMailbox:
        mb = await self.get_by_id(mailbox_id)
        if mb.status != "archived":
            raise HTTPException(status_code=409, detail="Only archived mailboxes can be restored")
        mb.status = "active"
        mb.archived_at = None
        await self.db.commit()
        await self.db.refresh(mb)

        from app.workers.mailbox_actors import restore_mailbox
        restore_mailbox.send(address=mb.address, mailbox_id=mb.id)
        log.info("mailbox_restore_enqueued", mailbox_id=mb.id, address=mb.address)
        return mb

    async def delete(self, mailbox_id: int) -> None:
        """Stage 2 of the two-step delete — only allowed when archived.

        Marks our row as `deleted` (kept as audit trail) and enqueues the
        actual Mailcow DELETE.
        """
        mb = await self.get_by_id(mailbox_id)
        if mb.status != "archived":
            raise HTTPException(
                status_code=409,
                detail="Mailbox must be archived before permanent deletion",
            )
        mb.status = "deleted"
        mb.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

        from app.workers.mailbox_actors import delete_mailbox
        delete_mailbox.send(address=mb.address, mailbox_id=mb.id)
        log.info("mailbox_delete_enqueued", mailbox_id=mb.id, address=mb.address)
