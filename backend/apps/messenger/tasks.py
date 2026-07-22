"""Celery background tasks for ``messenger`` — ported from
``services/messenger/app/workers/*.py`` (Dramatiq actors + APScheduler cron
jobs) and their underlying ``app/services/{history_archive,system_bots}.py``
(workers/admin sub-task, PLAN.md §6.5, the last messenger sub-task).

Every task below starts with ``require_service("messenger")`` — same pattern
as ``apps/mail/tasks.py``/``apps/cms/tasks.py`` — so a disabled ``messenger``
app stops processing queued/scheduled work too, not just HTTP requests
(``ServiceGateMiddleware`` only gates the request/response cycle).

Ported here:

  * ``archive_room_history``   — port of ``scheduler.py::archive_history_to_s3``
    (weekly S3 JSONL dump, ~Sat 04:30 GMT+5) + its underlying
    ``services/history_archive.py::archive_recent_history`` (now
    ``apps.messenger.services.history_archive_service``).
  * ``audit_log_compaction``   — port of ``scheduler.py::audit_log_compaction``
    (daily 03:30, real ``AuditLog`` reap past retention).
  * ``archive_old_messages``   — port of ``scheduler.py::archive_old_messages``
    (daily 03:15) — the source's OWN body is a log-only MVP stub ("MVP:
    только лог. TODO перенос в cold storage", verbatim comment in the
    FastAPI original) with no real archival logic to port; kept as a
    registered-but-DISABLED periodic task (same precedent as
    ``apps/media_files/tasks.py::cleanup_orphan_files`` / its migration
    ``0002_media_periodic_tasks.py`` — the schedule is documented intent, not
    invented behaviour).
  * ``dispatch_bot_message``   — Celery-task seam around
    ``services/system_bots.py::post_bot_message``. The FastAPI source has NO
    actor/task wrapping this call — ``app/api/v1/internal.py``'s
    ``/bot-message`` endpoint calls ``post_bot_message`` directly and
    ``await``s its result to answer the HTTP request synchronously (ported
    as-is: ``apps/messenger/views.py::internal_bot_message`` calls
    ``system_bots_service.post_bot_message`` inline, NOT this task, for the
    same reason — the response body needs ``delivered``/``message_id``
    immediately). This task exists as the async-enqueueable counterpart
    (``.delay(...)``) for callers that don't need to wait on the result —
    the closest genuine Celery-task home for what the brief calls
    "``system_bots``/``bot_dispatch`` (обработка бот-сообщений)". Not
    scheduled on beat (invoked ad hoc, same as the FastAPI original's
    Dramatiq actors were — none of THEM were on a cron either).
  * ``dispatch_push_notification`` — port of ``app/workers/actors.py::
    dispatch_push_notification`` (Dramatiq actor → Celery task). No-ops when
    neither FCM nor APNS is configured (``getattr(settings, ..., "")`` dev
    default, same settings-gated no-op style as ``apps/cms/tasks.py::
    translate_news``) — real network call is a documented seam, not
    implemented (no live FCM/APNS credentials exist in this repo/tests).

NOT ported here (documented, not silently dropped):

  * ``app/workers/bot_dispatch.py`` (Redis pub/sub subscriber turning
    ``notify.*`` channel events into templated bot-DM text) and
    ``app/workers/replica_sync.py`` (Redis pub/sub subscriber mirroring
    user-service lifecycle events into ``chat_user_replicas``) — both are
    long-running asyncio loops subscribed to Redis pub/sub, not queued
    Celery tasks, and BOTH depend on infrastructure this port does not carry
    forward: ``bot_dispatch.py``'s event publishers either don't exist yet in
    this monolith or, per PLAN.md §3, are replaced by direct in-process
    ``interface.py`` calls instead of Redis pub/sub (see
    ``apps.messenger.interface.dispatch_notification``'s own docstring for
    the replacement contract); ``replica_sync.py``'s target table
    (``chat_user_replicas``) is Р2 and never created here (see
    ``apps/messenger/models.py`` module docstring) — ``apps.users.interface``
    is the single source of truth instead, nothing to keep "in sync".
  * ``scheduler.py::cleanup_presence`` — the source's OWN body is a pure
    no-op ("Redis TTL handling — noop (presence хранится в Redis с TTL)",
    verbatim comment): unlike ``archive_old_messages`` above (an MVP stub
    documenting FUTURE intent), there is no future flip-the-switch moment
    here — presence in this port has no Redis-TTL mechanism of its own to
    "clean up" (``apps/messenger/socket.py`` never wrote one). A task that
    logs one string and does nothing else, forever, is pure scheduling
    noise — same reasoning ``apps/mail/tasks.py`` used to skip
    ``renew_push_subscriptions`` entirely (no driver to call, so no task to
    write), just applied to "nothing to clean up" instead of "no driver".
"""
from __future__ import annotations

import datetime
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.core.services import require_service
from apps.messenger.models import AuditLog

logger = logging.getLogger(__name__)


# ─── archive_room_history (port of scheduler.py::archive_history_to_s3) ────


@shared_task
def archive_room_history(days: int = 7) -> dict:
    """Weekly room-history → S3 JSONL dump.

    Port of ``scheduler.py::archive_history_to_s3``. Beat schedule: Saturday
    04:30 ``Asia/Almaty`` (GMT+5) — see ``apps/messenger/migrations/
    0003_messenger_periodic_tasks.py``, literal values from ``app/core/
    settings.py``'s ``history_archive_cron_{day,hour,minute}``/
    ``history_archive_timezone``. Delegates to ``services.
    history_archive_service.archive_recent_history`` — the SAME function the
    admin manual-backfill endpoint calls
    (``apps/messenger/views.py::admin_trigger_history_archive``), no
    duplicated logic.
    """
    require_service("messenger")

    from apps.messenger.services import history_archive_service

    summary = history_archive_service.archive_recent_history(days=days)
    logger.info("history_archive_done %s", summary)
    return summary


# ─── audit_log_compaction (port of scheduler.py::audit_log_compaction) ─────


@shared_task
def audit_log_compaction() -> int:
    """Reap ``AuditLog`` (messenger domain) rows past retention.

    Port of ``scheduler.py::audit_log_compaction`` — pure DB delete, no
    network involved. Shares the ``AUDIT_LOG_RETENTION_DAYS`` setting knob
    with ``apps.mail.tasks.audit_log_compaction`` (same literal default, 90,
    as the FastAPI messenger original's own ``settings.
    audit_log_retention_days`` — there is no per-domain retention config in
    either source, one shared Django setting covers both domains' identical
    default).
    """
    require_service("messenger")

    cutoff = timezone.now() - datetime.timedelta(
        days=getattr(settings, "AUDIT_LOG_RETENTION_DAYS", 90),
    )
    deleted, _ = AuditLog.objects.filter(created_at__lt=cutoff).delete()
    if deleted:
        logger.info("audit_log_compaction_run deleted=%d", deleted)
    return deleted


# ─── archive_old_messages (port of scheduler.py::archive_old_messages) ─────


@shared_task
def archive_old_messages() -> None:
    """Port of ``scheduler.py::archive_old_messages`` — the source's OWN
    body, verbatim: a log line, nothing else ("MVP: только лог. TODO перенос
    в cold storage"). Registered on beat but DISABLED (see migration
    ``0003_messenger_periodic_tasks.py``) — same precedent as
    ``apps.media_files.tasks.cleanup_orphan_files``: the schedule is kept as
    documentation of intent (daily 03:15 UTC, literal source cron), not
    invented cold-storage logic.
    """
    require_service("messenger")

    cutoff = timezone.now() - datetime.timedelta(days=90)
    logger.info("archive_old_messages_run cutoff=%s", cutoff.isoformat())


# ─── dispatch_bot_message (Celery seam around services/system_bots.py) ────


@shared_task(max_retries=3)
def dispatch_bot_message(user_id: int, bot_username: str, text: str, metadata: dict | None = None) -> str | None:
    """Async-enqueueable counterpart of ``system_bots_service.
    post_bot_message`` — see module docstring for why the internal HTTP
    endpoint calls that function directly instead of this task.

    Returns the created message's id (str) or ``None`` if the recipient
    doesn't resolve to a live user, or if ``bot_username`` isn't one of the
    known system bots (logged, not raised — a bad/unknown bot username is a
    caller bug, not worth crashing a queued task over).
    """
    require_service("messenger")

    from apps.messenger.services import system_bots_service

    bot = system_bots_service.BOTS_BY_USERNAME.get(bot_username)
    if bot is None:
        logger.warning("dispatch_bot_message_unknown_bot bot=%s", bot_username)
        return None

    msg = system_bots_service.post_bot_message(user_id=user_id, bot=bot, text=text, metadata=metadata)
    return str(msg.id) if msg is not None else None


# ─── dispatch_push_notification (port of app/workers/actors.py) ────────────


@shared_task(max_retries=3, retry_backoff=True)
def dispatch_push_notification(user_id: int, payload: dict) -> None:
    """Send FCM/APNS push. Port of ``app/workers/actors.py::
    dispatch_push_notification`` (Dramatiq actor → Celery task).

    No-ops when neither key is configured (``getattr(settings, ..., "")``
    dev default — Поток A does not touch ``htqweb/settings``, see CLAUDE.md)
    — same behaviour as the FastAPI original, and the network-free path this
    port's tests exercise (neither setting is defined anywhere in this repo
    yet). The real FCM/APNS HTTP call is a documented seam, same class of
    decision as ``apps/mail/tasks.py``'s un-ported sync drivers.
    """
    require_service("messenger")

    fcm_key = getattr(settings, "FCM_API_KEY", "")
    apns_cert = getattr(settings, "APNS_CERT_PATH", "")
    if not fcm_key and not apns_cert:
        logger.info("push_skipped_no_keys user_id=%s", user_id)
        return
    # TODO: real FCM/APNS call (буквальный порт исходника — тот же TODO там же)
    logger.info("push_dispatched user_id=%s", user_id)
