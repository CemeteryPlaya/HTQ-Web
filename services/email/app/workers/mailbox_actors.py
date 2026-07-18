"""Dramatiq actors that talk to Mailcow.

Each actor is idempotent w.r.t. the local row's `last_error` field:
on success → clear last_error; on failure → write the message and re-raise
so Dramatiq retries with backoff. After `max_retries` is exhausted Dramatiq
moves the message to the dead-letter queue and the row stays with
last_error set — admin sees it in the UI and can retry from there.

We do NOT run alembic-managed transactions inside actors; each actor opens
its own short-lived AsyncSession, mutates one row, commits.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dramatiq
import structlog
from sqlalchemy import select

from app.db import async_session_factory
from app.models.mailbox import ProvisionedMailbox
from app.services.mailcow_client import MailcowClient
from app.workers import broker  # noqa: F401  ensures broker is set before @actor


log = structlog.get_logger(__name__)


# ── DB helpers (open one session per actor invocation) ───────────────────────

async def _set_last_error(mailbox_id: int, message: str | None) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(ProvisionedMailbox).where(ProvisionedMailbox.id == mailbox_id))
        row = result.scalar_one_or_none()
        if not row:
            return
        if message is None and row.last_error is None:
            return
        row.last_error = message[:500] if message else None
        await db.commit()


def _run_or_record(mailbox_id: int, coro_factory) -> None:
    """Run an async block; on failure record last_error and re-raise."""
    try:
        asyncio.run(coro_factory())
        asyncio.run(_set_last_error(mailbox_id, None))
    except Exception as exc:  # noqa: BLE001 — Dramatiq retries via max_retries
        asyncio.run(_set_last_error(mailbox_id, repr(exc)))
        raise


# ── Actors ───────────────────────────────────────────────────────────────────


@dramatiq.actor(max_retries=5, min_backoff=2_000, max_backoff=60_000)
def provision_mailbox(
    *,
    mailbox_id: int,
    local_part: str,
    domain: str,
    password: str,
    full_name: str,
    quota_mb: int,
    force_change: bool,
) -> None:
    """Create the mailbox in Mailcow + provision an app-password.

    The app-password is what the IMAP IDLE supervisor (phase 6) and the
    SMTP sender (phase 7) authenticate with — Mailcow doesn't expose
    interactive passwords, so we must mint a separate one and stash the
    encrypted value on the row.
    """
    import secrets
    from app.services.crypto import crypto_service

    address = f"{local_part}@{domain}"

    async def _go():
        client = MailcowClient()
        await client.create_mailbox(
            local_part=local_part,
            domain=domain,
            password=password,
            full_name=full_name,
            quota_mb=quota_mb,
        )
        if force_change:
            await client.edit_mailbox(address, {"force_pw_update": "1"})
        log.info("mailbox_provisioned", mailbox_id=mailbox_id, address=address)

        # Best-effort app-password — failure here doesn't roll back the
        # mailbox itself. The supervisor + sender will retry / log warnings
        # if the password is missing.
        try:
            app_pwd = secrets.token_urlsafe(24)
            await client.add_app_password(
                address=address,
                app_name="htqweb-platform",
                password=app_pwd,
                protocols=["imap_access", "smtp_access"],
            )
            async with async_session_factory() as db:
                row = (
                    await db.execute(
                        select(ProvisionedMailbox).where(
                            ProvisionedMailbox.id == mailbox_id
                        )
                    )
                ).scalar_one_or_none()
                if row is not None:
                    row.encrypted_smtp_app_password = crypto_service.encrypt(app_pwd)
                    await db.commit()
            log.info("mailbox_app_password_set", mailbox_id=mailbox_id)
        except Exception as exc:
            log.warning(
                "mailbox_app_password_failed",
                mailbox_id=mailbox_id,
                err=str(exc),
            )

    _run_or_record(mailbox_id, _go)


@dramatiq.actor(max_retries=3, min_backoff=2_000)
def update_mailbox(*, address: str, attr: dict[str, Any], mailbox_id: int) -> None:
    async def _go():
        await MailcowClient().edit_mailbox(address, attr)
        log.info("mailbox_updated", mailbox_id=mailbox_id, address=address, attr=attr)

    _run_or_record(mailbox_id, _go)


@dramatiq.actor(max_retries=3, min_backoff=2_000)
def reset_mailbox_password(*, address: str, new_password: str, force_change: bool, mailbox_id: int) -> None:
    async def _go():
        await MailcowClient().reset_password(address, new_password, force_change=force_change)
        log.info("mailbox_password_reset", mailbox_id=mailbox_id, address=address)

    _run_or_record(mailbox_id, _go)


@dramatiq.actor(max_retries=3, min_backoff=2_000)
def archive_mailbox(*, address: str, mailbox_id: int) -> None:
    async def _go():
        await MailcowClient().set_active(address, active=False)
        log.info("mailbox_archived", mailbox_id=mailbox_id, address=address)

    _run_or_record(mailbox_id, _go)


@dramatiq.actor(max_retries=3, min_backoff=2_000)
def restore_mailbox(*, address: str, mailbox_id: int) -> None:
    async def _go():
        await MailcowClient().set_active(address, active=True)
        log.info("mailbox_restored", mailbox_id=mailbox_id, address=address)

    _run_or_record(mailbox_id, _go)


@dramatiq.actor(max_retries=3, min_backoff=2_000)
def delete_mailbox(*, address: str, mailbox_id: int) -> None:
    """Stage-2 final delete in Mailcow."""
    async def _go():
        await MailcowClient().delete_mailbox(address)
        log.info("mailbox_deleted_in_mailcow", mailbox_id=mailbox_id, address=address)

    _run_or_record(mailbox_id, _go)
