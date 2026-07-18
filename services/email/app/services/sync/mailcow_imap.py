"""Mailcow corporate sync via IMAP (one-shot polling).

For Phase 4 we connect, fetch the most recent N messages per canonical
mailbox, and disconnect. The long-running ``IMAP IDLE`` supervisor that
gives sub-10-second push lands in Phase 6 — it reuses the same parser
helpers below.

Requires Mailcow to expose IMAP (default 993 SSL) and a per-mailbox
app-password obtainable via ``POST /add/app-passwd``. Until phase 6
provisions those, the driver short-circuits when no credentials are set
on the ProvisionedMailbox row.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.account import EmailAccount
from app.models.mailbox import ProvisionedMailbox
from app.services.sync.base import SyncDriver, SyncResult
from app.services.sync.mapper import (
    imap_mailbox_to_folder,
    replace_attachments,
    upsert_message,
)


log = logging.getLogger(__name__)

# Folders we sync on initial backfill — mapped to canonical buckets in
# the mapper.
BACKFILL_MAILBOXES = ("INBOX", "Sent")


def _addresses(value: str | None) -> list[dict]:
    if not value:
        return []
    return [
        {"email": addr.lower(), "name": name}
        for name, addr in getaddresses([value])
        if addr
    ]


def _parse_eml(raw_bytes: bytes) -> dict:
    """Parse an RFC 5322 message into our common message dict shape."""
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

    sender_addrs = _addresses(msg.get("From"))
    sender_email = sender_addrs[0]["email"] if sender_addrs else ""
    sender_name = sender_addrs[0]["name"] if sender_addrs else None

    raw_date = msg.get("Date")
    try:
        date = parsedate_to_datetime(raw_date) if raw_date else None
    except Exception:
        date = None
    if not date:
        date = datetime.now(timezone.utc)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    body_html: str | None = None
    body_text: str | None = None
    attachments: list[dict] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment" or part.get_filename():
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": part.get_filename() or "attachment",
                    "mime_type": ctype or "application/octet-stream",
                    "size": len(payload),
                    "content_id": part.get("Content-ID"),
                }
            )
        elif ctype == "text/html" and body_html is None:
            try:
                body_html = part.get_content()
            except Exception:
                body_html = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )
        elif ctype == "text/plain" and body_text is None:
            try:
                body_text = part.get_content()
            except Exception:
                body_text = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )

    snippet = (body_text or "")[:255]

    return {
        "thread_id": msg.get("In-Reply-To") or msg.get("References") or None,
        "subject": msg.get("Subject", "") or "",
        "snippet": snippet,
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "to_recipients": _addresses(msg.get("To")),
        "cc_recipients": _addresses(msg.get("Cc")),
        "bcc_recipients": _addresses(msg.get("Bcc")),
        "date": date,
        "attachments": attachments,
        "rfc822_message_id": msg.get("Message-ID") or "",
    }


async def _open_imap(
    host: str, port: int, user: str, password: str, *, ssl: bool = True
):
    import aioimaplib

    cls = aioimaplib.IMAP4_SSL if ssl else aioimaplib.IMAP4
    client = cls(host=host, port=port, timeout=20)
    await client.wait_hello_from_server()
    typ, _ = await client.login(user, password)
    if typ != "OK":
        raise RuntimeError(f"IMAP login failed: {typ}")
    return client


async def _ids_in_mailbox(client, mailbox: str, limit: int) -> list[bytes]:
    typ, _ = await client.select(mailbox)
    if typ != "OK":
        return []
    typ, data = await client.uid("search", "ALL")
    if typ != "OK":
        return []
    raw_ids = data[0].split() if data and data[0] else []
    return raw_ids[-limit:]  # most recent N


async def _fetch_message(client, uid: bytes) -> bytes | None:
    typ, data = await client.uid("fetch", uid.decode(), "(RFC822 FLAGS)")
    if typ != "OK" or not data:
        return None
    # aioimaplib returns the literal as the second element.
    for chunk in data:
        if isinstance(chunk, (bytes, bytearray)) and chunk.startswith(b"From ") is False:
            if b"\r\n\r\n" in chunk or b"\n\n" in chunk:
                return bytes(chunk)
    return None


def _password_for(account: EmailAccount, mailbox: ProvisionedMailbox | None) -> str | None:
    """Resolve the IMAP password for the corporate account.

    Phase 6 will write a per-mailbox app-password into
    ``ProvisionedMailbox.encrypted_smtp_app_password``; until then, the
    driver returns ``None`` and the sync becomes a no-op.
    """
    if mailbox is None:
        return None
    enc = getattr(mailbox, "encrypted_smtp_app_password", None)
    if not enc:
        return None
    from app.services.crypto import crypto_service
    try:
        return crypto_service.decrypt(enc)
    except Exception:
        return None


class MailcowImapSyncDriver:
    provider = "mailcow"

    async def _do_sync(
        self,
        account: EmailAccount,
        session: AsyncSession,
        *,
        max_messages: int,
    ) -> SyncResult:
        result = SyncResult()
        if not (settings.mailcow_api_url and settings.mailcow_domain):
            result.errors.append("Mailcow not configured")
            return result

        mailbox = (
            await session.get(ProvisionedMailbox, account.mailbox_id)
            if account.mailbox_id
            else None
        )
        password = _password_for(account, mailbox)
        if not password:
            result.errors.append(
                "No app-password stored — phase 6 provisioning required"
            )
            log.info(
                "mailcow_sync_skipped account=%s — no app-password yet", account.id
            )
            account.last_sync_error = "missing_app_password"
            await session.flush()
            return result

        # Resolve IMAP host from settings (Mailcow's mail.* host).
        imap_host = (
            settings.mailcow_api_url.replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
        )
        imap_port = 993
        per_mailbox = max(10, max_messages // len(BACKFILL_MAILBOXES))
        uidvalidity_map: dict[str, str] = {}
        uidnext_map: dict[str, str] = {}

        client = await _open_imap(
            host=imap_host,
            port=imap_port,
            user=account.address,
            password=password,
            ssl=True,
        )
        try:
            for raw_mailbox in BACKFILL_MAILBOXES:
                folder, provider_folder = imap_mailbox_to_folder(raw_mailbox)
                uids = await _ids_in_mailbox(client, raw_mailbox, per_mailbox)

                # Pick up UIDVALIDITY / UIDNEXT from the SELECT response
                # (Phase 6 will rely on this for incremental).
                typ, status = await client.status(
                    raw_mailbox, "(UIDNEXT UIDVALIDITY)"
                )
                if typ == "OK" and status:
                    text = b" ".join(status).decode(errors="ignore")
                    for token in ("UIDVALIDITY", "UIDNEXT"):
                        idx = text.find(token + " ")
                        if idx >= 0:
                            tail = text[idx + len(token) + 1 :]
                            value = tail.split(" ", 1)[0].split(")", 1)[0]
                            (uidvalidity_map if token == "UIDVALIDITY" else uidnext_map)[
                                raw_mailbox
                            ] = value

                for uid in uids:
                    raw = await _fetch_message(client, uid)
                    if not raw:
                        result.skipped += 1
                        continue
                    try:
                        parsed = _parse_eml(raw)
                    except Exception as exc:
                        result.errors.append(f"parse uid={uid!r}: {exc}")
                        result.skipped += 1
                        continue

                    rfc822_msg_id = parsed.pop("rfc822_message_id") or f"imap:{uid.decode()}"
                    attachments = parsed.pop("attachments", [])

                    msg_uuid, was_inserted = await upsert_message(
                        session,
                        user_id=account.user_id,
                        account_id=account.id,
                        message_id=rfc822_msg_id,
                        folder=folder,
                        provider_folder=provider_folder,
                        is_read=False,
                        is_flagged=False,
                        has_attachments=bool(attachments),
                        **parsed,
                    )
                    if was_inserted:
                        result.inserted += 1
                    else:
                        result.updated += 1
                    if attachments:
                        result.attachments_saved += await replace_attachments(
                            session, msg_uuid, attachments
                        )
        finally:
            try:
                await client.logout()
            except Exception:
                pass

        account.sync_state = {
            **(account.sync_state or {}),
            "uidvalidity": uidvalidity_map,
            "uidnext": uidnext_map,
        }
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        await session.flush()
        return result

    async def initial_backfill(
        self, account, session, *, max_messages
    ) -> SyncResult:
        return await self._do_sync(account, session, max_messages=max_messages)

    async def incremental(self, account, session, *, hint=None) -> SyncResult:
        # No real delta yet — re-poll the most recent N. Phase 6 IDLE
        # supervisor will slot in here with proper UID-tracking.
        return await self._do_sync(
            account, session, max_messages=settings.sync_initial_backfill_count
        )

    async def register_push(self, account, session):  # phase 6 (IDLE)
        return None

    async def renew_push(self, account, session):
        return None

    async def unregister_push(self, account, session):
        return None
