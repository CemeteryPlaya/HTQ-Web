"""Dramatiq actors for email service."""
import asyncio
import uuid

import dramatiq
from sqlalchemy import update

from app.workers import broker  # noqa: F401
from app.core.logging import get_logger

# Import side-effect: register the per-account sync actors with the broker
# so that `dramatiq app.workers.actors` discovers them too.
from app.workers import sync_actors  # noqa: F401

log = get_logger(__name__)


async def _do_deliver(message_uuid: uuid.UUID) -> None:
    """Look up the message + account and dispatch to the right Sender."""
    from app.db import async_session_factory
    from app.models.account import EmailAccount
    from app.models.email import EmailMessage, RecipientStatus
    from app.services.sender import get_sender

    async with async_session_factory() as session:
        msg = await session.get(EmailMessage, message_uuid)
        if msg is None:
            log.warning("deliver_email_not_found", message_id=str(message_uuid))
            return
        if msg.account_id is None:
            log.warning("deliver_email_no_account", message_id=str(message_uuid))
            return
        account = await session.get(EmailAccount, msg.account_id)
        if account is None or not account.is_active:
            await session.execute(
                update(EmailMessage)
                .where(EmailMessage.id == msg.id)
                .values(folder="outbox")
            )
            await session.commit()
            raise RuntimeError("account inactive")

        sender = get_sender(account.provider)
        result = await sender.send(account, msg, session)

        # Mark every per-recipient row.
        rec_status = "sent" if result.ok else "bounced"
        await session.execute(
            update(RecipientStatus)
            .where(RecipientStatus.message_id == msg.id)
            .values(
                status=rec_status,
                error_message=result.error if not result.ok else None,
            )
        )

        if result.ok:
            msg.folder = "sent"
            if result.provider_message_id:
                msg.message_id = result.provider_message_id
            if result.provider_thread_id:
                msg.thread_id = result.provider_thread_id
            await session.commit()
            log.info("delivered", message_id=str(msg.id), account_id=msg.account_id)
            # Reconcile Sent folder with provider state on next sync.
            try:
                from app.workers.sync_actors import incremental_sync_account
                incremental_sync_account.send(msg.account_id)
            except Exception:
                pass
        else:
            msg.folder = "outbox"
            await session.commit()
            log.warning(
                "deliver_failed",
                message_id=str(msg.id),
                err=result.error,
            )
            raise RuntimeError(result.error)


@dramatiq.actor(max_retries=5, min_backoff=1000, max_backoff=30000)
def deliver_email(message_id: str) -> None:
    """Deliver one queued message via the right provider Sender."""
    asyncio.run(_do_deliver(uuid.UUID(message_id)))


@dramatiq.actor(max_retries=3)
def dlp_scan_attachment(attachment_id: int) -> None:
    """Scan attachment for sensitive data."""
    log.info("dlp_scanning_attachment", attachment_id=attachment_id)
    # TODO: real DLP scan logic
