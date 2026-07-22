"""Event dispatch — de-duplicated notification per recipient, plus SSE fan-out.

Ported from ``services/requests/app/services/dispatch.py``. Three things
happened there and still happen here, in the same order:

1. a ``NotificationsLog`` row is inserted, keyed by
   ``(request, step, kind, recipient)`` — the row IS the de-duplication, so a
   retried dispatch cannot ping the same person twice for the same event;
2. the message is delivered to the user;
3. the event is published to Redis so an open SSE stream updates live.

What changed (decision Р2 / PLAN.md §6.2): delivery was a Dramatiq actor
posting to the messenger bot; it now goes through
``apps.messenger.interface.dispatch_notification``. That neighbour belongs to
Поток A and is still a prep stub, so the call degrades — **the workflow must
never fail because a notification could not be delivered**. Same for the SSE
publish: it is a UX optimisation, and the DB row is the source of truth.

The de-duplication row is written BEFORE delivery is attempted. That ordering
is deliberate: an undelivered notification is a missed ping, but a
double-written row after a partial failure would mean the next retry stays
silent forever.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

from django.conf import settings as django_settings
from django.db import IntegrityError, transaction

from apps.core.services import ServiceDisabled
from apps.messenger import interface as messenger_interface

from ..models import NotificationsLog

logger = logging.getLogger(__name__)


def _build_text(kind: str, instance, **ctx) -> str:
    """Message wording, copied value-for-value — users recognise these."""
    code = instance.code
    if kind == "request_assigned":
        amount = instance.total_amount or 0
        return (f"🧾 Новый запрос {code} от пользователя "
                f"#{instance.initiator_id} (сумма {amount}) ждёт вашего "
                f"согласования.")
    if kind == "approved_partial":
        return f"✅ #{ctx.get('approver_id')} одобрил шаг по запросу {code}."
    if kind == "request_changes":
        return (f"↩️ #{ctx.get('approver_id')} вернул запрос {code} на "
                f"доработку: «{ctx.get('comment', '')}».")
    if kind == "rejected":
        return (f"❌ Запрос {code} отклонён (#{ctx.get('approver_id')}). "
                f"Причина: «{ctx.get('comment', '')}».")
    if kind == "approved_final":
        return f"✅ Запрос {code} полностью одобрен."
    if kind == "cancelled":
        return (f"🚫 Инициатор #{ctx.get('actor_id', instance.initiator_id)} "
                f"отменил запрос {code}.")
    if kind == "reminder":
        return f"⏰ Напоминание: запрос {code} всё ещё ждёт вашего ответа."
    if kind == "escalation":
        return (f"🚨 Эскалация: запрос {code} простаивает слишком долго и "
                f"нуждается во внимании администратора.")
    return f"Запрос {code}: событие {kind}"


def _meta(instance, kind: str) -> dict:
    return {
        "kind": kind,
        "request_id": instance.id,
        "request_code": instance.code,
        "deep_link": f"/requests/{instance.id}",
    }


def sse_channel(user_id: int) -> str:
    return f"requests:user:{user_id}"


def publish_sse(user_id: int, kind: str, payload: dict) -> None:
    """Best-effort publish to the user's SSE channel.

    Failures are logged and swallowed: an unavailable Redis must not fail an
    approval that has already been written.
    """
    try:
        import redis

        client = redis.Redis.from_url(
            getattr(django_settings, "REDIS_URL", "redis://localhost:6379/0"))
        try:
            client.publish(sse_channel(user_id),
                           json.dumps({"event": kind, **payload}))
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sse_publish_failed user=%s kind=%s err=%s",
                       user_id, kind, exc)


def _deliver(user_id: int, text: str, payload: dict) -> None:
    """Hand the message to messenger, degrading if it cannot take it."""
    try:
        messenger_interface.dispatch_notification([user_id],
                                                  {"text": text, **payload})
    except ServiceDisabled:
        logger.debug("approvals: messenger disabled, notification not sent")
    except NotImplementedError:
        # Prep-4.0 stub until Поток A implements it (PLAN.md §6.5).
        logger.debug("approvals: messenger interface is still a prep stub")
    except Exception:
        logger.exception("approvals: notification delivery failed")


def dispatch_event(instance, kind: str, recipients: Iterable[int],
                   **ctx) -> list[int]:
    """Notify ``recipients`` once each about ``kind``.

    Returns the ids actually notified (i.e. those not already de-duplicated),
    which the tests assert on and which keeps the function useful to callers
    that want to know whether anything was sent.
    """
    step = instance.current_node_id or "final"
    payload = _meta(instance, kind)
    text = _build_text(kind, instance, **ctx)
    notified: list[int] = []

    for user_id in sorted({int(u) for u in recipients}):
        dedup = f"{instance.id}:{step}:{kind}:{user_id}"
        try:
            # The unique index on dedup_key does the work; a savepoint keeps
            # a lost race from poisoning the caller's transaction.
            with transaction.atomic():
                NotificationsLog.objects.create(
                    request=instance, recipient_id=user_id, kind=kind,
                    channel="bot", dedup_key=dedup)
        except IntegrityError:
            continue          # already notified for this exact event
        notified.append(user_id)
        _deliver(user_id, text, payload)
        publish_sse(user_id, kind, payload)
    return notified
