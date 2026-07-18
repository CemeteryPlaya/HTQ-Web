"""Synchronous S2S client for the messenger internal endpoint."""

import httpx

from app.core.settings import settings


class MessengerS2SError(Exception):
    pass


def post_bot_message_sync(*, bot: str, user_id: int, text: str, metadata: dict | None = None) -> None:
    url = settings.messenger_internal_url.rstrip("/") + "/api/messenger/v1/internal/bot-message"
    headers = {"X-Internal-Token": settings.messenger_internal_token}
    body = {"bot": bot, "user_id": user_id, "text": text, "metadata": metadata}
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        raise MessengerS2SError(f"messenger unreachable: {exc}") from exc
    if resp.status_code >= 500:
        raise MessengerS2SError(f"messenger returned {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise MessengerS2SError(f"messenger rejected payload ({resp.status_code}): {resp.text[:200]}")
