"""Gmail API sender — POST users.messages.send with base64url MIME. Порт
``services/email/app/services/sender/gmail.py``.

SYNC (``httpx.Client``, не ``AsyncClient``) — тот же принцип, что
``apps/mail/services/oauth_clients.py``. Токен — через
``apps/mail/services/sync/gmail.py::ensure_fresh_token`` (тот же импорт-путь,
что в исходнике: ``from app.services.sync.gmail import _ensure_fresh_token``).

Единственный живой HTTP-вызов обёрнут в module-level seam ``_post_send`` —
тесты монkeypatch'ят именно его."""
from __future__ import annotations

import logging

import httpx

from apps.mail.services.sender.base import SendResult
from apps.mail.services.sender.mime import build_mime, to_base64url
from apps.mail.services.sync.gmail import ensure_fresh_token

log = logging.getLogger(__name__)
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _post_send(access_token: str, body: dict) -> httpx.Response:
    """Сеам для тестов — единственная строчка, которая идёт в реальную сеть."""
    with httpx.Client(timeout=30.0) as client:
        return client.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )


class GmailSender:
    provider = "google"

    def send(self, account, message) -> SendResult:
        access_token = ensure_fresh_token(account)
        mime = build_mime(
            message, from_address=account.address, from_name=account.display_name,
        )
        body: dict = {"raw": to_base64url(mime)}
        if message.thread_id:
            body["threadId"] = message.thread_id

        response = _post_send(access_token, body)
        if response.status_code >= 400:
            return SendResult(error=f"gmail {response.status_code}: {response.text[:300]}")
        data = response.json()
        return SendResult(
            provider_message_id=data.get("id"),
            provider_thread_id=data.get("threadId"),
        )
