"""Microsoft Graph sender — POST /me/sendMail."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import EmailAccount
from app.models.email import EmailMessage
from app.services.sender.base import SendResult
from app.services.sync.microsoft import _ensure_fresh_token


log = logging.getLogger(__name__)
SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


def _recipients(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs or []:
        addr = r.get("email")
        if not addr:
            continue
        entry = {"emailAddress": {"address": addr}}
        if r.get("name"):
            entry["emailAddress"]["name"] = r["name"]
        out.append(entry)
    return out


class GraphSender:
    provider = "microsoft"

    async def send(
        self,
        account: EmailAccount,
        message: EmailMessage,
        session: AsyncSession,
    ) -> SendResult:
        access_token = await _ensure_fresh_token(session, account)

        body_content = message.body_html or message.body_text or ""
        body_type = "html" if message.body_html else "text"

        payload = {
            "message": {
                "subject": message.subject or "",
                "body": {"contentType": body_type, "content": body_content},
                "toRecipients": _recipients(message.to_recipients),
                "ccRecipients": _recipients(message.cc_recipients),
                "bccRecipients": _recipients(message.bcc_recipients),
            },
            "saveToSentItems": True,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
            if r.status_code >= 400:
                return SendResult(error=f"graph {r.status_code}: {r.text[:300]}")
        # /sendMail returns 202 with no body — Graph fills the message_id
        # asynchronously; we capture conversationId on the next sync delta.
        return SendResult()
