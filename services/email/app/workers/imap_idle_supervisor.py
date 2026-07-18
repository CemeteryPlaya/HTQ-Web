"""IMAP IDLE supervisor for corporate (Mailcow) accounts.

Runs as its own container — opens one IMAP IDLE session per active
corporate ``EmailAccount`` and enqueues ``incremental_sync_account``
whenever the server pushes ``EXISTS`` / ``EXPUNGE`` events.

Lifecycle:
  * On startup: SELECT all corporate accounts where ``is_active=true``
    and a Mailcow app-password is stored. Spawn one ``asyncio`` task per
    account.
  * Per-account loop: connect → LOGIN → SELECT INBOX → IDLE; on any
    server line that contains ``EXISTS`` or ``EXPUNGE``, enqueue an
    incremental sync. Renew the IDLE every 28 minutes (RFC 2177 limit
    is 30 — leave a margin).
  * Listen on Redis pub/sub channel ``email.account.changed`` for
    add/drop signals so newly-provisioned mailboxes start streaming
    without a process restart.
  * Exponential backoff on connect failures; permanent failure parks the
    account until the supervisor is restarted.

Run:
    python -m app.workers.imap_idle_supervisor
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import structlog

from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.core.settings import settings


log = structlog.get_logger(__name__)


CHANNEL = "email.account.changed"
IDLE_RENEW_SECONDS = 28 * 60
RECONNECT_BACKOFF_BASE = 5
RECONNECT_BACKOFF_MAX = 300


def _imap_host() -> str:
    """Resolve IMAP host from MAILCOW_API_URL (mail.<domain>)."""
    if not settings.mailcow_api_url:
        return ""
    return (
        settings.mailcow_api_url.replace("https://", "")
        .replace("http://", "")
        .split("/")[0]
    )


async def _resolve_account_creds(account_id: int):
    """Look up address + decrypted IMAP app-password for an account."""
    from app.db import async_session_factory
    from app.models.account import EmailAccount
    from app.models.mailbox import ProvisionedMailbox
    from app.services.crypto import crypto_service

    async with async_session_factory() as session:
        acc = await session.get(EmailAccount, account_id)
        if acc is None or acc.provider != "mailcow" or not acc.is_active:
            return None
        if not acc.mailbox_id:
            return None
        mb = await session.get(ProvisionedMailbox, acc.mailbox_id)
        if mb is None or not mb.encrypted_smtp_app_password:
            return None
        try:
            password = crypto_service.decrypt(mb.encrypted_smtp_app_password)
        except Exception:
            return None
        return acc.address, password


async def _idle_loop(account_id: int) -> None:
    """One long-lived IDLE session per account. Cancellation-safe."""
    import aioimaplib

    host = _imap_host()
    if not host:
        log.warning("idle_no_host account_id=%s — MAILCOW_API_URL empty", account_id)
        return

    backoff = RECONNECT_BACKOFF_BASE
    while True:
        creds = await _resolve_account_creds(account_id)
        if creds is None:
            log.info("idle_account_unprovisioned", account_id=account_id)
            return
        address, password = creds

        try:
            client = aioimaplib.IMAP4_SSL(host=host, port=993, timeout=30)
            await client.wait_hello_from_server()
            typ, _ = await client.login(address, password)
            if typ != "OK":
                raise RuntimeError(f"login failed: {typ}")
            typ, _ = await client.select("INBOX")
            if typ != "OK":
                raise RuntimeError(f"select INBOX failed: {typ}")

            log.info("idle_connected", account_id=account_id, address=address)
            backoff = RECONNECT_BACKOFF_BASE  # reset after a clean connect

            while True:
                idle = await client.idle_start(timeout=IDLE_RENEW_SECONDS)
                # Drain any events that landed before we re-armed.
                while True:
                    try:
                        line = await asyncio.wait_for(
                            client.wait_server_push(), timeout=IDLE_RENEW_SECONDS
                        )
                    except asyncio.TimeoutError:
                        break
                    if line and any(
                        kw in (line if isinstance(line, str) else " ".join(line))
                        for kw in ("EXISTS", "EXPUNGE", "FETCH")
                    ):
                        log.info(
                            "idle_event_fired",
                            account_id=account_id,
                            line=str(line)[:80],
                        )
                        from app.workers.sync_actors import incremental_sync_account
                        incremental_sync_account.send(account_id)

                client.idle_done()
                await asyncio.wait_for(idle, timeout=10)
                # Brief pause before re-IDLE — keeps tight loops out of the
                # picture if the server hangs up immediately.
                await asyncio.sleep(0.1)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "idle_connection_lost",
                account_id=account_id,
                err=str(exc),
                backoff=backoff,
            )
            try:
                await client.logout()
            except Exception:
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)


class Supervisor:
    """Owns the per-account IDLE tasks and reacts to live add/drop signals."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[Any]] = {}

    async def add(self, account_id: int) -> None:
        if account_id in self._tasks and not self._tasks[account_id].done():
            return
        log.info("supervisor_spawn", account_id=account_id)
        self._tasks[account_id] = asyncio.create_task(
            _idle_loop(account_id), name=f"idle-{account_id}"
        )

    async def drop(self, account_id: int) -> None:
        task = self._tasks.pop(account_id, None)
        if task is None:
            return
        log.info("supervisor_drop", account_id=account_id)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def hydrate(self) -> None:
        """Spawn IDLE tasks for every currently-active corporate account."""
        from app.db import async_session_factory
        from app.models.account import EmailAccount
        from sqlalchemy import select

        async with async_session_factory() as session:
            ids = (
                await session.execute(
                    select(EmailAccount.id).where(
                        EmailAccount.provider == "mailcow",
                        EmailAccount.is_active.is_(True),
                    )
                )
            ).scalars().all()
        for account_id in ids:
            await self.add(account_id)

    async def listen_for_changes(self) -> None:
        """Subscribe to ``email.account.changed`` and react to events.

        Payload shape: ``{"account_id": <int>, "action": "add"|"drop"}``.
        Other services can publish to this channel after creating /
        archiving an EmailAccount so the supervisor reflects it without a
        full restart.
        """
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(CHANNEL)
        log.info("supervisor_subscribed", channel=CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg.get("data") or "{}")
                except json.JSONDecodeError:
                    continue
                action = data.get("action")
                account_id = int(data.get("account_id", 0))
                if not account_id:
                    continue
                if action == "add":
                    await self.add(account_id)
                elif action == "drop":
                    await self.drop(account_id)
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()


async def main() -> None:
    configure_logging()
    if not settings.mailcow_api_url:
        log.info("imap_idle_supervisor_disabled — MAILCOW_API_URL not set")
        # Sleep forever so the container stays "up" without busy-restarting.
        while True:
            await asyncio.sleep(3600)

    sup = Supervisor()
    await sup.hydrate()
    await sup.listen_for_changes()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
