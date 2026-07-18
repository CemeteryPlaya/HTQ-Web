"""Event dispatch — inserts a dedup row, enqueues the bot actor, and publishes
to Redis for SSE fan-out."""

from __future__ import annotations

import json
import logging
from typing import Iterable

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.notifications_log import NotificationsLog
from app.models.request_instance import RequestInstance
from app.workers.notifications import send_bot_message

_BOT = "bot-requests"
_log = logging.getLogger(__name__)

# Lazy-initialised async Redis client for the SSE pub/sub fan-out. Created on
# first publish so unit tests that monkeypatch `_redis_client` keep working.
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.Redis.from_url(settings.redis_url)
    return _redis_client


def _build_text(kind: str, inst: RequestInstance, **ctx) -> str:
    code = inst.code
    if kind == "request_assigned":
        amt = inst.total_amount or 0
        return f"🧾 Новый запрос {code} от пользователя #{inst.initiator_id} (сумма {amt}) ждёт вашего согласования."
    if kind == "approved_partial":
        return f"✅ #{ctx.get('approver_id')} одобрил шаг по запросу {code}."
    if kind == "request_changes":
        return f"↩️ #{ctx.get('approver_id')} вернул запрос {code} на доработку: «{ctx.get('comment', '')}»."
    if kind == "rejected":
        return f"❌ Запрос {code} отклонён (#{ctx.get('approver_id')}). Причина: «{ctx.get('comment', '')}»."
    if kind == "approved_final":
        return f"✅ Запрос {code} полностью одобрен."
    if kind == "cancelled":
        return f"🚫 Инициатор #{ctx.get('actor_id', inst.initiator_id)} отменил запрос {code}."
    if kind == "reminder":
        return f"⏰ Напоминание: запрос {code} всё ещё ждёт вашего ответа."
    if kind == "escalation":
        return f"🚨 Эскалация: запрос {code} простаивает слишком долго и нуждается во внимании администратора."
    return f"Запрос {code}: событие {kind}"


def _meta(inst: RequestInstance, kind: str) -> dict:
    return {
        "kind": kind,
        "request_id": inst.id,
        "request_code": inst.code,
        "deep_link": f"/requests/{inst.id}",
    }


async def _publish_sse(uid: int, kind: str, payload: dict) -> None:
    """Publish to ``requests:user:{uid}`` so SSE subscribers see the update.

    Best-effort: failures are logged but never propagate (the bot DM and DB log
    are the source of truth — SSE is a UX optimisation)."""
    try:
        client = _get_redis()
        await client.publish(f"requests:user:{uid}", json.dumps({"event": kind, **payload}))
    except Exception as exc:  # noqa: BLE001
        _log.warning("sse_publish_failed user=%s kind=%s err=%s", uid, kind, exc)


async def dispatch_event(
    session: AsyncSession,
    inst: RequestInstance,
    kind: str,
    recipients: Iterable[int],
    **ctx,
) -> None:
    """Insert a dedup row per (recipient, step, kind), enqueue the bot actor,
    and publish to Redis for the SSE stream.

    Cross-DB-safe dedup via SELECT-then-INSERT (good enough at dev concurrency)."""
    step = inst.current_node_id or "final"
    payload = _meta(inst, kind)
    for uid in {int(u) for u in recipients}:
        dedup = f"{inst.id}:{step}:{kind}:{uid}"
        exists = await session.execute(
            select(NotificationsLog.id).where(NotificationsLog.dedup_key == dedup)
        )
        if exists.first() is not None:
            continue
        session.add(NotificationsLog(
            request_id=inst.id, recipient_id=uid, kind=kind, channel="bot", dedup_key=dedup,
        ))
        await session.flush()
        text = _build_text(kind, inst, **ctx)
        send_bot_message.send_with_options(args=[_BOT, uid, text, payload])
        await _publish_sse(uid, kind, payload)
