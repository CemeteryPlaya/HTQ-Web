"""APScheduler jobs for email-service.

Run as separate process:
    python -m app.workers.scheduler
"""
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.db import async_session_factory
from app.models.account import EmailAccount
from app.models.audit_log import AuditLog
from app.models.email import OAuthToken

log = get_logger(__name__)


async def imap_poll_fallback() -> None:
    """Catch-all poll for accounts the push subscription has missed.

    Picks corporate Mailcow accounts whose ``last_sync_at`` is older than
    2 minutes (the IMAP IDLE supervisor in Phase 6 should keep things
    fresh; this is the safety net for the period it's down). Personal
    accounts are skipped — Pub/Sub / Graph webhooks own their delta.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(EmailAccount.id).where(
                    EmailAccount.provider == "mailcow",
                    EmailAccount.is_active.is_(True),
                    (EmailAccount.last_sync_at.is_(None))
                    | (EmailAccount.last_sync_at < cutoff),
                )
            )
        ).scalars().all()

    if not rows:
        return
    from app.workers.sync_actors import incremental_sync_account
    for account_id in rows:
        incremental_sync_account.send(account_id)
    log.info("imap_poll_fallback enqueued=%d", len(rows))


async def oauth_token_refresh() -> None:
    """Refresh access_tokens that expire in the next 15 minutes."""
    from datetime import timedelta as _td
    from app.services.crypto import crypto_service
    from app.services.oauth_clients import get_oauth_client

    threshold = datetime.now(timezone.utc) + _td(minutes=15)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(OAuthToken).where(
                    OAuthToken.is_active.is_(True),
                    OAuthToken.expires_at <= threshold,
                    OAuthToken.encrypted_refresh_token.is_not(None),
                )
            )
        ).scalars().all()

        refreshed = 0
        for token in rows:
            try:
                client = get_oauth_client(token.provider)
                refresh = crypto_service.decrypt(token.encrypted_refresh_token)
                bundle = await client.refresh(refresh)
                token.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
                if bundle.refresh_token:
                    token.encrypted_refresh_token = crypto_service.encrypt(
                        bundle.refresh_token
                    )
                token.expires_at = datetime.now(timezone.utc) + _td(
                    seconds=bundle.expires_in
                )
                refreshed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("oauth_refresh_failed token=%s: %s", token.id, exc)
        await session.commit()
    if refreshed:
        log.info("oauth_token_refresh refreshed=%d", refreshed)


async def renew_push_subscriptions() -> None:
    """Push subscriptions expire — renew the ones close to TTL.

    Triggers ``renew_account_watch`` actor for any active account whose
    ``watch_expires_at`` falls within 24 hours.
    """
    cutoff = datetime.now(timezone.utc) + timedelta(hours=24)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(EmailAccount.id).where(
                    EmailAccount.is_active.is_(True),
                    EmailAccount.watch_expires_at.is_not(None),
                    EmailAccount.watch_expires_at < cutoff,
                )
            )
        ).scalars().all()
    if not rows:
        return
    from app.workers.sync_actors import renew_account_watch
    for account_id in rows:
        renew_account_watch.send(account_id)
    log.info("renew_push_subscriptions enqueued=%d", len(rows))


async def final_purge_archived_mailboxes() -> None:
    """Stage-2 of the user-delete cascade.

    Picks every ProvisionedMailbox whose status is 'archived' and whose
    archived_at is older than MAILBOX_PURGE_AFTER_DAYS, marks the row
    as 'deleted' and enqueues the Mailcow hard-delete actor. Set the
    env to 0 to test the cascade end-to-end immediately.
    """
    from app.models.mailbox import ProvisionedMailbox

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.mailbox_purge_after_days)
    purged = 0
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ProvisionedMailbox).where(
                    ProvisionedMailbox.status == "archived",
                    ProvisionedMailbox.archived_at < cutoff,
                )
            )
        ).scalars().all()
        for mb in rows:
            mb.status = "deleted"
            mb.deleted_at = datetime.now(timezone.utc)
            purged += 1
        if purged:
            await session.commit()
            try:
                from app.workers.mailbox_actors import delete_mailbox
                for mb in rows:
                    delete_mailbox.send(address=mb.address, mailbox_id=mb.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("final_purge_enqueue_failed", err=str(exc))
    if purged:
        log.info("final_purge_archived_mailboxes purged=%d", purged)


async def audit_log_compaction() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)
    async with async_session_factory() as s:
        result = await s.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await s.commit()
        log.info("audit_log_compaction_run", deleted=result.rowcount)


async def _run_forever() -> None:
    """Start APScheduler inside a running loop — required under Python 3.14."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(imap_poll_fallback, "interval", seconds=60, id="imap_poll_fallback")
    scheduler.add_job(oauth_token_refresh, "interval", minutes=5, id="oauth_token_refresh")
    scheduler.add_job(renew_push_subscriptions, "interval", minutes=30, id="renew_push_subscriptions")
    scheduler.add_job(final_purge_archived_mailboxes, "cron", hour=3, minute=15, id="final_purge_archived_mailboxes")
    scheduler.add_job(audit_log_compaction, "cron", hour=3, minute=30, id="audit_log_compaction")
    scheduler.start()
    log.info("apscheduler_started")
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(_run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
