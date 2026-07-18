"""Redis subscriber that turns notify.* events into bot DM messages.

Each event channel maps to a specific system bot (see
``app.services.system_bots.SYSTEM_BOTS``).  The handler unpacks the
payload into a human-readable line and calls ``post_bot_message`` —
which auto-creates the user↔bot DM on first delivery and broadcasts via
Socket.IO so the sidebar reflects the new message in real time.

Channels and payload shapes are documented next to each handler.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
import structlog

from app.core.settings import settings
from app.services.system_bots import (
    BOT_CALENDAR,
    BOT_EMAIL,
    BOT_FILES,
    BOT_NEWS,
    BOT_TASKS,
    post_bot_message,
)


log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------
CHANNEL_CALENDAR_REMINDER = "notify.calendar_event_reminder"
CHANNEL_TASK_STATUS = "notify.task_status_changed"
CHANNEL_EMAIL_NEW = "notify.new_email_message"
CHANNEL_FILE_ACCESS = "notify.file_access_request"
CHANNEL_NEWS_DEPT = "notify.news_for_department"


async def _handle_calendar(payload: dict[str, Any]) -> None:
    """Payload: ``{user_id, title, starts_in_minutes, room_id?, event_id, location?}``"""
    user_id = payload.get("user_id")
    if not user_id:
        return
    title = payload.get("title") or "событие"
    when = payload.get("starts_in_minutes")
    location = (payload.get("location") or "").strip()
    when_str = (
        f"через {int(when)} мин." if isinstance(when, (int, float)) and when > 0
        else "уже сейчас"
    )
    text = f"🔔 Напоминание: «{title}» начнётся {when_str}."
    if location:
        text += f"\nМесто: {location}"
    await post_bot_message(
        user_id=int(user_id),
        bot=BOT_CALENDAR,
        text=text,
        metadata={"event_id": payload.get("event_id")},
    )


async def _handle_task_status(payload: dict[str, Any]) -> None:
    """Payload: ``{user_id, task_key, summary, from_status, to_status, actor_name}``"""
    user_id = payload.get("user_id")
    if not user_id:
        return
    key = payload.get("task_key") or "(?)"
    summary = (payload.get("summary") or "").strip()
    to_status = payload.get("to_status") or "обновлён"
    actor = (payload.get("actor_name") or "").strip()
    title = f"{key}: {summary}" if summary else key
    by_clause = f" пользователем {actor}" if actor else ""
    text = f"Статус задачи «{title}» изменён на «{to_status}»{by_clause}."
    await post_bot_message(
        user_id=int(user_id),
        bot=BOT_TASKS,
        text=text,
        metadata={"task_key": key, "to_status": to_status},
    )


async def _handle_email(payload: dict[str, Any]) -> None:
    """Payload: published by email-service after a new inbox message lands.
    ``{user_id, subject, sender_email, sender_name, snippet, message_uuid}``"""
    user_id = payload.get("user_id")
    if not user_id:
        return
    subject = (payload.get("subject") or "(без темы)").strip()
    sender = (payload.get("sender_name") or payload.get("sender_email") or "").strip()
    snippet = (payload.get("snippet") or "").strip()
    header = f"📧 Новое письмо от {sender}" if sender else "📧 Новое письмо"
    text = f"{header}\nТема: {subject}"
    if snippet:
        text += f"\n\n{snippet[:200]}"
    await post_bot_message(
        user_id=int(user_id),
        bot=BOT_EMAIL,
        text=text,
        metadata={"message_uuid": payload.get("message_uuid")},
    )


async def _handle_file_access(payload: dict[str, Any]) -> None:
    """Payload: ``{user_id, requester_name, file_name, department_name?, file_id?}``

    Emitted by hr-service when someone uploads or requests access to a
    file in the recipient's department folder.
    """
    user_id = payload.get("user_id")
    if not user_id:
        return
    requester = (payload.get("requester_name") or "Сотрудник").strip()
    file_name = (payload.get("file_name") or "файл").strip()
    dept = (payload.get("department_name") or "").strip()
    text = f"{requester} загрузил(а) файл «{file_name}»"
    if dept:
        text += f" в отдел «{dept}»"
    await post_bot_message(
        user_id=int(user_id),
        bot=BOT_FILES,
        text=text,
        metadata={"file_id": payload.get("file_id")},
    )


async def _handle_news(payload: dict[str, Any]) -> None:
    """Payload: ``{title, slug, excerpt?, department_name?, user_ids?}``

    Published by cms-service when a news article transitions to
    ``published=True``. When ``user_ids`` is supplied, we deliver only to
    those recipients; otherwise the bot fans out to every active non-bot
    replica row (= every employee with a messenger account).
    """
    title = (payload.get("title") or "Новость").strip()
    dept = (payload.get("department_name") or "").strip()
    excerpt = (payload.get("excerpt") or "").strip()
    slug = payload.get("slug")
    header = "📰 Новость"
    if dept:
        header += f" для «{dept}»"
    body = f"{header}\n{title}"
    if excerpt:
        body += f"\n\n{excerpt[:240]}"

    recipient_ids: list[int]
    explicit = payload.get("user_ids")
    if isinstance(explicit, list) and explicit:
        recipient_ids = [int(uid) for uid in explicit]
    else:
        # No targeted audience — broadcast to every active human in the
        # messenger replica.
        from sqlalchemy import select as _select

        from app.db import async_session_factory
        from app.models.domain import ChatUserReplica

        async with async_session_factory() as session:
            rows = await session.execute(
                _select(ChatUserReplica.id).where(
                    ChatUserReplica.is_active.is_(True),
                    ChatUserReplica.is_bot.is_(False),
                )
            )
            recipient_ids = [int(r) for r, in rows.all()]

    for uid in recipient_ids:
        await post_bot_message(
            user_id=uid,
            bot=BOT_NEWS,
            text=body,
            metadata={"news_slug": slug},
        )


HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {
    CHANNEL_CALENDAR_REMINDER: _handle_calendar,
    CHANNEL_TASK_STATUS: _handle_task_status,
    CHANNEL_EMAIL_NEW: _handle_email,
    CHANNEL_FILE_ACCESS: _handle_file_access,
    CHANNEL_NEWS_DEPT: _handle_news,
}


async def _dispatch(channel: str, raw: bytes | str) -> None:
    handler = HANDLERS.get(channel)
    if handler is None:
        return
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("bot_dispatch_bad_json", channel=channel)
        return
    try:
        await handler(payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("bot_dispatch_handler_error", channel=channel, err=str(exc))


async def run_bot_dispatch_loop() -> None:
    """Long-running subscriber. Reconnects on transient Redis errors."""
    backoff = 1
    while True:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(*HANDLERS.keys())
            log.info("bot_dispatch_subscribed", channels=list(HANDLERS.keys()))
            backoff = 1
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                channel = msg.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")
                await _dispatch(channel, msg.get("data") or b"")
        except asyncio.CancelledError:
            try:
                await pubsub.unsubscribe()
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
            log.info("bot_dispatch_stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("bot_dispatch_disconnected", err=str(exc), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
