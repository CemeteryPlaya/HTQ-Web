"""Microsoft Graph sender — POST /me/sendMail. Порт
``services/email/app/services/sender/graph.py``.

Токен — через ``apps/mail/services/sync/microsoft.py::ensure_fresh_token``
(тот же импорт-путь, что в исходнике). Единственный живой HTTP-вызов — через
seam ``_post_send``, монkeypatch'ится в тестах."""
from __future__ import annotations

import logging

import httpx

from apps.mail.services.sender.base import SendResult
from apps.mail.services.sync.microsoft import ensure_fresh_token

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


def _post_send(access_token: str, payload: dict) -> httpx.Response:
    """Сеам для тестов — единственная строчка, которая идёт в реальную сеть."""
    with httpx.Client(timeout=30.0) as client:
        return client.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )


class GraphSender:
    provider = "microsoft"

    def send(self, account, message) -> SendResult:
        access_token = ensure_fresh_token(account)

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

        response = _post_send(access_token, payload)
        if response.status_code >= 400:
            return SendResult(error=f"graph {response.status_code}: {response.text[:300]}")
        # /sendMail returns 202 with no body — Graph fills the message_id
        # asynchronously; captured on the next sync delta (not ported here).
        return SendResult()
