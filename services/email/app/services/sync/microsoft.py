"""Microsoft Graph mail sync driver.

* Initial backfill: ``/me/mailFolders/{folder}/messages?$top=N`` per
  canonical folder (Inbox / SentItems).
* Incremental: ``/me/mailFolders/Inbox/messages/delta``; persists the
  returned ``@odata.deltaLink`` in ``account.sync_state["delta_link"]``.

Provider quirks:
* Personal Outlook accounts may have ``mail`` field as ``null`` — fall
  back to ``userPrincipalName`` (handled in oauth_clients.userinfo).
* Body comes pre-extracted as ``body.content`` (HTML) plus
  ``bodyPreview`` (text snippet).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.account import EmailAccount
from app.models.email import OAuthToken
from app.services.crypto import crypto_service
from app.services.oauth_clients import MicrosoftOAuthClient
from app.services.sync.base import SyncDriver, SyncResult
from app.services.sync.mapper import (
    graph_folder_to_folder,
    replace_attachments,
    upsert_message,
)


log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"

# Well-known folder names used in /me/mailFolders/{name}.
BACKFILL_FOLDERS = ["inbox", "sentitems"]

SELECT = (
    "id,internetMessageId,conversationId,subject,bodyPreview,body,"
    "from,toRecipients,ccRecipients,bccRecipients,receivedDateTime,"
    "sentDateTime,isRead,flag,hasAttachments,parentFolderId"
)


def _addresses(recipients: list[dict] | None) -> list[dict]:
    if not recipients:
        return []
    out = []
    for r in recipients:
        addr = (r.get("emailAddress") or {})
        email = (addr.get("address") or "").lower()
        if email:
            out.append({"email": email, "name": addr.get("name")})
    return out


def _ingest(raw: dict, folder_name: str) -> dict:
    folder, provider_folder = graph_folder_to_folder(folder_name)
    body = raw.get("body") or {}
    body_html = body.get("content") if body.get("contentType") == "html" else None
    body_text = body.get("content") if body.get("contentType") == "text" else None

    sender_obj = (raw.get("from") or {}).get("emailAddress") or {}
    received = raw.get("receivedDateTime") or raw.get("sentDateTime")
    try:
        date = (
            datetime.fromisoformat(received.replace("Z", "+00:00"))
            if received
            else datetime.now(timezone.utc)
        )
    except Exception:
        date = datetime.now(timezone.utc)

    flag_status = ((raw.get("flag") or {}).get("flagStatus") or "").lower()

    return {
        "message_id": raw["id"],
        "thread_id": raw.get("conversationId"),
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": raw.get("subject", ""),
        "snippet": raw.get("bodyPreview", ""),
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": (sender_obj.get("address") or "").lower(),
        "sender_name": sender_obj.get("name"),
        "to_recipients": _addresses(raw.get("toRecipients")),
        "cc_recipients": _addresses(raw.get("ccRecipients")),
        "bcc_recipients": _addresses(raw.get("bccRecipients")),
        "is_read": bool(raw.get("isRead", False)),
        "is_flagged": flag_status == "flagged",
        "has_attachments": bool(raw.get("hasAttachments", False)),
        "date": date,
        "attachments": [],  # phase 7 fetches via /messages/{id}/attachments
    }


async def _ensure_fresh_token(
    session: AsyncSession, account: EmailAccount
) -> str:
    token_row = await session.get(OAuthToken, account.oauth_token_id)
    if token_row is None:
        raise RuntimeError(f"OAuthToken missing for account {account.id}")
    if token_row.expires_at and token_row.expires_at <= datetime.now(timezone.utc):
        if not token_row.encrypted_refresh_token:
            raise RuntimeError("Microsoft access token expired and no refresh_token")
        refresh = crypto_service.decrypt(token_row.encrypted_refresh_token)
        bundle = await MicrosoftOAuthClient().refresh(refresh)
        token_row.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
        if bundle.refresh_token:
            token_row.encrypted_refresh_token = crypto_service.encrypt(bundle.refresh_token)
        from datetime import timedelta
        token_row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=bundle.expires_in)
        await session.flush()
    return crypto_service.decrypt(token_row.encrypted_access_token)


class MicrosoftSyncDriver:
    provider = "microsoft"

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
        per_folder = max(10, max_messages // len(BACKFILL_FOLDERS))

        async with httpx.AsyncClient(timeout=30.0) as client:
            for folder_name in BACKFILL_FOLDERS:
                url: str | None = (
                    f"{GRAPH}/me/mailFolders/{folder_name}/messages"
                    f"?$top={min(50, per_folder)}&$select={SELECT}&$orderby=receivedDateTime desc"
                )
                fetched = 0
                while url and fetched < per_folder:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 404:
                        result.errors.append(f"folder {folder_name} missing")
                        break
                    r.raise_for_status()
                    data = r.json()
                    for raw in data.get("value", []):
                        parsed = _ingest(raw, folder_name)
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
                        fetched += 1
                        if fetched >= per_folder:
                            break
                    url = data.get("@odata.nextLink") if fetched < per_folder else None

        # Capture an initial Inbox delta link so the next incremental knows
        # where to start.
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{GRAPH}/me/mailFolders/inbox/messages/delta?$select={SELECT}"
            delta_link = None
            while url:
                r = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
                if r.status_code != 200:
                    break
                data = r.json()
                if data.get("@odata.deltaLink"):
                    delta_link = data["@odata.deltaLink"]
                    break
                url = data.get("@odata.nextLink")
            if delta_link:
                account.sync_state = {**(account.sync_state or {}), "delta_link": delta_link}

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
        delta_link = (account.sync_state or {}).get("delta_link")
        if not delta_link:
            return await self.initial_backfill(
                account, session, max_messages=settings.sync_initial_backfill_count
            )

        access_token = await _ensure_fresh_token(session, account)
        headers = {"Authorization": f"Bearer {access_token}"}

        url: str | None = delta_link
        new_delta: str | None = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while url:
                r = await client.get(url, headers=headers)
                if r.status_code == 410:  # delta expired
                    log.info("graph_delta_expired account=%s — re-baselining", account.id)
                    return await self.initial_backfill(
                        account,
                        session,
                        max_messages=settings.sync_initial_backfill_count,
                    )
                r.raise_for_status()
                data = r.json()
                for raw in data.get("value", []):
                    if raw.get("@removed"):
                        from sqlalchemy import delete as sa_delete
                        from app.models.email import EmailMessage

                        await session.execute(
                            sa_delete(EmailMessage).where(
                                EmailMessage.account_id == account.id,
                                EmailMessage.message_id == raw["id"],
                            )
                        )
                        result.deleted += 1
                        continue
                    parsed = _ingest(raw, "inbox")
                    parsed.pop("attachments", None)
                    _, was_inserted = await upsert_message(
                        session,
                        user_id=account.user_id,
                        account_id=account.id,
                        **parsed,
                    )
                    if was_inserted:
                        result.inserted += 1
                    else:
                        result.updated += 1
                if data.get("@odata.deltaLink"):
                    new_delta = data["@odata.deltaLink"]
                    url = None
                else:
                    url = data.get("@odata.nextLink")

        if new_delta:
            account.sync_state = {**(account.sync_state or {}), "delta_link": new_delta}
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        await session.flush()
        return result

    async def register_push(self, account, session):
        from datetime import datetime, timedelta, timezone

        if not (settings.webhook_base_url and settings.microsoft_webhook_client_state):
            log.info(
                "graph_register_push_skipped account=%s — webhook config missing",
                account.id,
            )
            return None
        access = await _ensure_fresh_token(session, account)
        client = MicrosoftOAuthClient()
        notification_url = (
            f"{settings.webhook_base_url.rstrip('/')}"
            "/api/email/v1/webhooks/microsoft"
        )
        # Graph requires UTC ISO with trailing 'Z'.
        exp_dt = datetime.now(timezone.utc) + timedelta(
            minutes=settings.push_subscription_ttl_minutes
        )
        exp_iso = exp_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        result = await client.create_subscription(
            access,
            resource="/me/mailFolders('Inbox')/messages",
            notification_url=notification_url,
            client_state=settings.microsoft_webhook_client_state,
            expiration_iso=exp_iso,
        )
        account.sync_state = {
            **(account.sync_state or {}),
            "subscription_id": result.get("id", ""),
        }
        account.watch_expires_at = exp_dt
        await session.flush()

    async def renew_push(self, account, session):
        from datetime import datetime, timedelta, timezone

        sub_id = (account.sync_state or {}).get("subscription_id")
        if not sub_id:
            return await self.register_push(account, session)
        access = await _ensure_fresh_token(session, account)
        exp_dt = datetime.now(timezone.utc) + timedelta(
            minutes=settings.push_subscription_ttl_minutes
        )
        exp_iso = exp_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
            await MicrosoftOAuthClient().renew_subscription(
                access, subscription_id=sub_id, expiration_iso=exp_iso
            )
            account.watch_expires_at = exp_dt
            await session.flush()
        except Exception as exc:
            log.warning("graph_renew_failed account=%s: %s — re-registering", account.id, exc)
            await self.register_push(account, session)

    async def unregister_push(self, account, session):
        sub_id = (account.sync_state or {}).get("subscription_id")
        if not sub_id:
            return
        try:
            access = await _ensure_fresh_token(session, account)
            await MicrosoftOAuthClient().delete_subscription(access, sub_id)
        except Exception as exc:
            log.warning("graph_delete_subscription_failed account=%s: %s", account.id, exc)
        account.watch_expires_at = None
        if account.sync_state:
            new_state = dict(account.sync_state)
            new_state.pop("subscription_id", None)
            account.sync_state = new_state
        await session.flush()
