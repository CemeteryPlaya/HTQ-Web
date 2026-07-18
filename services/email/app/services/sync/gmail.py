"""Gmail API sync driver.

* Initial backfill: ``users.messages.list?labelIds=INBOX|SENT|...&maxResults=N``
  → fan out to ``users.messages.get`` for each id, UPSERT.
* Incremental: ``users.history.list?startHistoryId=...``. On 404 (history
  gap > 1 week), re-baseline via ``messages.list?q=newer_than:7d``.

Body extraction: walks the MIME tree (``payload.parts``) to pull
``text/html`` and ``text/plain`` parts. Attachments are listed but not
downloaded here — phase 7 send-pipeline downloads on demand from
``users.messages.attachments.get``.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.account import EmailAccount
from app.models.email import OAuthToken
from app.services.crypto import crypto_service
from app.services.oauth_clients import GoogleOAuthClient
from app.services.sync.base import SyncDriver, SyncResult
from app.services.sync.mapper import (
    gmail_labels_to_folder,
    replace_attachments,
    upsert_message,
)


log = logging.getLogger(__name__)


GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

# Folders we sync on backfill — Drafts intentionally omitted (we sync via
# label filter on incremental once the user starts using compose).
BACKFILL_LABELS = ["INBOX", "SENT"]


def _b64url_decode(data: str) -> bytes:
    """Gmail uses URL-safe base64 without padding."""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _parse_addresses(value: str | None) -> list[dict]:
    if not value:
        return []
    return [
        {"email": addr.lower(), "name": name}
        for name, addr in getaddresses([value])
        if addr
    ]


def _walk_parts(payload: dict) -> tuple[str | None, str | None, list[dict]]:
    """Returns (body_html, body_text, attachments)."""
    body_html: str | None = None
    body_text: str | None = None
    attachments: list[dict] = []

    def visit(part: dict) -> None:
        nonlocal body_html, body_text
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        filename = part.get("filename") or ""
        data = body.get("data")

        if filename:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": mime or "application/octet-stream",
                    "size": int(body.get("size", 0)),
                    "content_id": next(
                        (
                            h["value"]
                            for h in part.get("headers", [])
                            if h.get("name", "").lower() == "content-id"
                        ),
                        None,
                    ),
                }
            )
        elif mime == "text/html" and data and body_html is None:
            body_html = _b64url_decode(data).decode("utf-8", errors="replace")
        elif mime == "text/plain" and data and body_text is None:
            body_text = _b64url_decode(data).decode("utf-8", errors="replace")

        for sub in part.get("parts", []) or []:
            visit(sub)

    visit(payload)
    return body_html, body_text, attachments


async def _ensure_fresh_token(
    session: AsyncSession, account: EmailAccount
) -> str:
    """Decrypt access token; refresh if expired."""
    token_row = await session.get(OAuthToken, account.oauth_token_id)
    if token_row is None:
        raise RuntimeError(f"OAuthToken missing for account {account.id}")

    if token_row.expires_at and token_row.expires_at <= datetime.now(timezone.utc):
        if not token_row.encrypted_refresh_token:
            raise RuntimeError("Access token expired and no refresh_token stored")
        refresh = crypto_service.decrypt(token_row.encrypted_refresh_token)
        bundle = await GoogleOAuthClient().refresh(refresh)
        token_row.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
        if bundle.refresh_token:
            token_row.encrypted_refresh_token = crypto_service.encrypt(bundle.refresh_token)
        from datetime import timedelta
        token_row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=bundle.expires_in)
        await session.flush()

    return crypto_service.decrypt(token_row.encrypted_access_token)


async def _get_message(client: httpx.AsyncClient, headers: dict, msg_id: str) -> dict:
    """Fetch a single Gmail message in `metadata` then `full` if needed.

    We use ``format=full`` directly — the body parts come down with the
    same call, saving a round-trip per message.
    """
    r = await client.get(
        f"{GMAIL_API}/messages/{msg_id}",
        headers=headers,
        params={"format": "full"},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()


def _ingest_message_payload(raw: dict) -> dict:
    """Convert a Gmail API message payload to mapper.upsert_message kwargs."""
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    folder, provider_folder = gmail_labels_to_folder(raw.get("labelIds", []))

    body_html, body_text, attachments = _walk_parts(payload)

    raw_date = headers.get("date")
    try:
        date = parsedate_to_datetime(raw_date) if raw_date else None
    except Exception:
        date = None
    if not date:
        # `internalDate` is ms since epoch.
        ts = int(raw.get("internalDate", 0)) / 1000
        date = datetime.fromtimestamp(ts, tz=timezone.utc)

    sender_email = ""
    sender_name = None
    from_addrs = _parse_addresses(headers.get("from"))
    if from_addrs:
        sender_email = from_addrs[0]["email"]
        sender_name = from_addrs[0]["name"] or None

    return {
        "message_id": raw["id"],
        "thread_id": raw.get("threadId"),
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": headers.get("subject", ""),
        "snippet": raw.get("snippet", ""),
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "to_recipients": _parse_addresses(headers.get("to")),
        "cc_recipients": _parse_addresses(headers.get("cc")),
        "bcc_recipients": _parse_addresses(headers.get("bcc")),
        "is_read": "UNREAD" not in (raw.get("labelIds") or []),
        "is_flagged": "STARRED" in (raw.get("labelIds") or []),
        "has_attachments": bool(attachments),
        "date": date,
        "attachments": attachments,
    }


class GmailSyncDriver:
    provider = "google"

    async def initial_backfill(
        self,
        account: EmailAccount,
        session: AsyncSession,
        *,
        max_messages: int,
    ) -> SyncResult:
        result = SyncResult()
        access_token = await _ensure_fresh_token(session, account)
        headers = {"Authorization": f"Bearer {access_token}"}

        per_label = max(10, max_messages // len(BACKFILL_LABELS))

        async with httpx.AsyncClient(timeout=30.0) as client:
            highest_history_id: str | None = None
            for label in BACKFILL_LABELS:
                ids: list[str] = []
                page_token: str | None = None
                while len(ids) < per_label:
                    params = {
                        "labelIds": label,
                        "maxResults": min(100, per_label - len(ids)),
                    }
                    if page_token:
                        params["pageToken"] = page_token
                    r = await client.get(
                        f"{GMAIL_API}/messages",
                        headers=headers,
                        params=params,
                    )
                    r.raise_for_status()
                    data = r.json()
                    ids.extend(m["id"] for m in data.get("messages", []))
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break

                for msg_id in ids:
                    try:
                        raw = await _get_message(client, headers, msg_id)
                    except httpx.HTTPError as exc:
                        result.errors.append(f"GET {msg_id}: {exc}")
                        result.skipped += 1
                        continue

                    if highest_history_id is None or int(raw.get("historyId", 0)) > int(
                        highest_history_id
                    ):
                        highest_history_id = raw.get("historyId")

                    parsed = _ingest_message_payload(raw)
                    attachments = parsed.pop("attachments", [])

                    msg_uuid, was_inserted = await upsert_message(
                        session,
                        user_id=account.user_id,
                        account_id=account.id,
                        **parsed,
                    )
                    if was_inserted:
                        result.inserted += 1
                    else:
                        result.updated += 1
                    if attachments:
                        n = await replace_attachments(session, msg_uuid, attachments)
                        result.attachments_saved += n

        # Persist sync_state baseline.
        if highest_history_id:
            account.sync_state = {
                **(account.sync_state or {}),
                "history_id": str(highest_history_id),
            }
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        await session.flush()
        return result

    async def incremental(
        self,
        account: EmailAccount,
        session: AsyncSession,
        *,
        hint: dict | None = None,
    ) -> SyncResult:
        result = SyncResult()
        state = account.sync_state or {}
        start_history = (hint or {}).get("history_id") or state.get("history_id")
        if not start_history:
            # No baseline — degrade to full backfill (but cheaper).
            return await self.initial_backfill(
                account,
                session,
                max_messages=settings.sync_initial_backfill_count,
            )

        access_token = await _ensure_fresh_token(session, account)
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            page_token: str | None = None
            ids_to_fetch: set[str] = set()
            ids_to_delete: set[str] = set()
            new_history_id: str | None = None

            while True:
                params: dict[str, Any] = {"startHistoryId": start_history}
                if page_token:
                    params["pageToken"] = page_token
                r = await client.get(
                    f"{GMAIL_API}/history",
                    headers=headers,
                    params=params,
                )
                if r.status_code == 404:
                    # Gmail expired the history — re-baseline.
                    log.info(
                        "gmail_history_gap account=%s — re-baselining", account.id
                    )
                    return await self.initial_backfill(
                        account,
                        session,
                        max_messages=settings.sync_initial_backfill_count,
                    )
                r.raise_for_status()
                data = r.json()
                new_history_id = data.get("historyId") or new_history_id
                for entry in data.get("history", []):
                    for added in entry.get("messagesAdded", []):
                        ids_to_fetch.add(added["message"]["id"])
                    for ld in entry.get("labelsAdded", []):
                        ids_to_fetch.add(ld["message"]["id"])
                    for lr in entry.get("labelsRemoved", []):
                        ids_to_fetch.add(lr["message"]["id"])
                    for deleted in entry.get("messagesDeleted", []):
                        ids_to_delete.add(deleted["message"]["id"])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            for msg_id in ids_to_fetch:
                try:
                    raw = await _get_message(client, headers, msg_id)
                except httpx.HTTPError as exc:
                    if "404" in str(exc):
                        ids_to_delete.add(msg_id)
                        continue
                    result.errors.append(f"GET {msg_id}: {exc}")
                    result.skipped += 1
                    continue

                parsed = _ingest_message_payload(raw)
                attachments = parsed.pop("attachments", [])
                msg_uuid, was_inserted = await upsert_message(
                    session,
                    user_id=account.user_id,
                    account_id=account.id,
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

            if ids_to_delete:
                from sqlalchemy import delete as sa_delete
                from app.models.email import EmailMessage

                stmt = sa_delete(EmailMessage).where(
                    EmailMessage.account_id == account.id,
                    EmailMessage.message_id.in_(ids_to_delete),
                )
                deleted = (await session.execute(stmt)).rowcount or 0
                result.deleted += int(deleted)

        if new_history_id:
            account.sync_state = {
                **(account.sync_state or {}),
                "history_id": str(new_history_id),
            }
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        await session.flush()
        return result

    async def register_push(self, account, session):
        from datetime import datetime, timezone

        if not settings.google_pubsub_topic:
            log.info(
                "gmail_register_push_skipped account=%s — no GOOGLE_PUBSUB_TOPIC",
                account.id,
            )
            return None
        access = await _ensure_fresh_token(session, account)
        client = GoogleOAuthClient()
        result = await client.start_watch(
            access,
            topic=settings.google_pubsub_topic,
            label_ids=["INBOX", "SENT"],
        )
        # `expiration` is ms since epoch as string.
        try:
            exp = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=timezone.utc)
        except Exception:
            exp = None
        account.sync_state = {
            **(account.sync_state or {}),
            "watch_topic": settings.google_pubsub_topic,
            "history_id": str(result.get("historyId", "")),
        }
        account.watch_expires_at = exp
        await session.flush()

    async def renew_push(self, account, session):
        # Gmail watch is renewed by re-issuing it (idempotent).
        return await self.register_push(account, session)

    async def unregister_push(self, account, session):
        try:
            access = await _ensure_fresh_token(session, account)
            await GoogleOAuthClient().stop_watch(access)
        except Exception as exc:
            log.warning("gmail_stop_watch_failed account=%s: %s", account.id, exc)
        account.watch_expires_at = None
        if account.sync_state and "watch_topic" in account.sync_state:
            new_state = dict(account.sync_state)
            new_state.pop("watch_topic", None)
            account.sync_state = new_state
        await session.flush()
