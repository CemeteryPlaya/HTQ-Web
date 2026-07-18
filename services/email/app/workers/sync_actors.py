"""Dramatiq actors that run the per-account sync drivers.

Patterns:
* Each actor is a sync wrapper that opens its own ``AsyncSession`` and
  drives the async driver with ``asyncio.run``.
* A Postgres advisory lock keyed on ``account_id`` serialises concurrent
  runs (manual refresh + scheduled poll, etc.) so neither race nor
  deadlock — second caller observes the lock and exits cleanly.
* Errors stamp ``account.last_sync_error`` and re-raise so Dramatiq's
  retry/backoff applies.
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
from sqlalchemy import text

from app.core.settings import settings
from app.db import async_session_factory
from app.models.account import EmailAccount
from app.services.sync import get_driver

# Re-uses the broker registered in app.workers.__init__
from app.workers import broker  # noqa: F401


log = logging.getLogger(__name__)


# Stable namespace for advisory locks (keeps email locks separate from
# whatever else might use the same DB). pg_try_advisory_lock takes two
# 32-bit ints — first one is the namespace.
_ADVISORY_NAMESPACE = 0x454D4149  # 'EMAI'


async def _run(account_id: int, *, mode: str, hint: dict | None = None) -> None:
    async with async_session_factory() as session:
        # Advisory lock — non-blocking try_advisory_lock returns false if
        # another worker is already syncing this account.
        got = (
            await session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :acc)"),
                {"ns": _ADVISORY_NAMESPACE, "acc": account_id},
            )
        ).scalar_one()
        if not got:
            log.info("sync_skipped_locked account=%s mode=%s", account_id, mode)
            return

        try:
            account = await session.get(EmailAccount, account_id)
            if account is None:
                log.warning("sync_account_missing account=%s", account_id)
                return
            if not account.is_active:
                log.info("sync_skipped_inactive account=%s", account_id)
                return

            driver = get_driver(account.provider)
            try:
                if mode == "initial":
                    result = await driver.initial_backfill(
                        account,
                        session,
                        max_messages=settings.sync_initial_backfill_count,
                    )
                else:
                    result = await driver.incremental(account, session, hint=hint)
                await session.commit()
                log.info(
                    "sync_done account=%s mode=%s inserted=%d updated=%d "
                    "deleted=%d skipped=%d errors=%d",
                    account_id,
                    mode,
                    result.inserted,
                    result.updated,
                    result.deleted,
                    result.skipped,
                    len(result.errors),
                )
            except Exception as exc:
                await session.rollback()
                # Re-load the account in this fresh transaction and stamp
                # the error so the UI surfaces it; then re-raise so
                # Dramatiq retries.
                err_text = str(exc)[:500] or exc.__class__.__name__
                acc_for_err = await session.get(EmailAccount, account_id)
                if acc_for_err is not None:
                    acc_for_err.last_sync_error = err_text
                    await session.commit()
                log.exception(
                    "sync_failed account=%s mode=%s err=%s",
                    account_id,
                    mode,
                    err_text[:120],
                )
                raise
        finally:
            try:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:ns, :acc)"),
                    {"ns": _ADVISORY_NAMESPACE, "acc": account_id},
                )
                await session.commit()
            except Exception:  # never mask the original failure
                await session.rollback()


@dramatiq.actor(max_retries=3, min_backoff=2_000, max_backoff=60_000, time_limit=300_000)
def start_account_sync(account_id: int) -> None:
    """Initial backfill of a freshly-connected account.

    Phase 5 will append push registration after a successful first run.
    """
    asyncio.run(_run(account_id, mode="initial"))


@dramatiq.actor(max_retries=5, min_backoff=2_000, max_backoff=60_000, time_limit=180_000)
def incremental_sync_account(account_id: int, hint_history_id: str | None = None) -> None:
    """Pull the delta since the last cursor."""
    hint = {"history_id": hint_history_id} if hint_history_id else None
    asyncio.run(_run(account_id, mode="incremental", hint=hint))


async def _push_action(account_id: int, action: str) -> None:
    """Run register/renew/unregister on the account's driver."""
    async with async_session_factory() as session:
        account = await session.get(EmailAccount, account_id)
        if account is None:
            return
        driver = get_driver(account.provider)
        try:
            if action == "register":
                await driver.register_push(account, session)
            elif action == "renew":
                await driver.renew_push(account, session)
            elif action == "unregister":
                await driver.unregister_push(account, session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@dramatiq.actor(max_retries=3, min_backoff=2_000, max_backoff=60_000)
def register_account_push(account_id: int) -> None:
    """Initial push subscription after a successful first sync."""
    asyncio.run(_push_action(account_id, "register"))


@dramatiq.actor(max_retries=3, min_backoff=2_000, max_backoff=60_000)
def renew_account_watch(account_id: int) -> None:
    """Refresh push subscription before expiry (scheduler-driven)."""
    asyncio.run(_push_action(account_id, "renew"))


@dramatiq.actor(max_retries=2, min_backoff=2_000)
def stop_account_sync(account_id: int) -> None:
    """Tear down push subscription on disconnect."""
    asyncio.run(_push_action(account_id, "unregister"))
