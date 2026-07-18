"""Gmail API sender — POST users.messages.send with base64url MIME."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import EmailAccount
from app.models.email import EmailMessage
from app.services.sender.base import SendResult
from app.services.sender.mime import build_mime, to_base64url
from app.services.sync.gmail import _ensure_fresh_token  # reuse refresh logic


log = logging.getLogger(__name__)
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailSender:
    provider = "google"

    async def send(
        self,
        account: EmailAccount,
        message: EmailMessage,
        session: AsyncSession,
    ) -> SendResult:
        access_token = await _ensure_fresh_token(session, account)
        mime = build_mime(
            message,
            from_address=account.address,
            from_name=account.display_name,
        )
        body: dict = {"raw": to_base64url(mime)}
        if message.thread_id:
            body["threadId"] = message.thread_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            if r.status_code >= 400:
                return SendResult(error=f"gmail {r.status_code}: {r.text[:300]}")
            data = r.json()
        return SendResult(
            provider_message_id=data.get("id"),
            provider_thread_id=data.get("threadId"),
        )
