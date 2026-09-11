"""Celery background tasks for ``mail`` — ported from
``services/email/app/workers/{actors,sync_actors,scheduler}.py`` (Dramatiq
actors + APScheduler cron jobs).

Every task below starts with ``require_service("mail")`` — same pattern as
``apps/cms/tasks.py``/``apps/media_files/tasks.py`` — so a disabled ``mail``
app stops processing queued/scheduled work too, not just HTTP requests
(``ServiceGateMiddleware`` only gates the request/response cycle).

Scope of THIS port (workers sub-task, PLAN.md §6.4 — the last mail sub-task):
only the actors/scheduler jobs explicitly called out in its brief:

  * ``deliver_email``               — port of ``actors.py::deliver_email``.
  * ``incremental_sync_account``    — port of ``sync_actors.py::
    incremental_sync_account`` (the actor the 3 webhook receivers enqueue).
  * ``dlp_scan_attachment``         — port of ``actors.py::dlp_scan_attachment``.
  * ``final_purge_archived_mailboxes`` — port of ``scheduler.py`` (~03:15 UTC).
  * ``audit_log_compaction``        — port of ``scheduler.py`` (~03:30 UTC).
  * ``imap_poll_fallback``          — port of ``scheduler.py`` (every 60s).
  * ``oauth_token_refresh``         — port of ``scheduler.py`` (every 5 min).

NOT ported here (documented, not silently dropped):

  * ``sync_actors.py::start_account_sync``/``register_account_push``/
    ``renew_account_watch``/``stop_account_sync`` and
    ``scheduler.py::renew_push_subscriptions`` — all depend on the
    per-provider ``SyncDriver`` (``initial_backfill``/``incremental``/
    ``register_push``/``renew_push``/``unregister_push``), which
    ``apps/mail/services/sync/base.py``'s docstring already documents as
    NOT ported (Р2, mail-messages sub-task) — only the payload MAPPERS
    (``gmail.py``/``microsoft.py``/``mailcow_imap.py``/``mapper.py``) made the
    trip, unit-tested on recorded payloads, no live network. With no driver
    to call, there is nothing for these tasks to do; inventing a body would
    be fabricating behaviour the brief explicitly scoped out (Р3: "провайдеры
    — seam без живой сети", "mailcow/провайдеры — seam"). Same reasoning
    covers ``workers/imap_idle_supervisor.py`` (its own process, not a task —
    see ``apps/mail/management/commands/run_imap_idle.py``) and
    ``workers/user_events.py``'s Redis pub/sub subscriber (superseded by
    ``apps.mail.interface.archive_user_mailboxes``, see that module).
  * ``mailbox_actors.py`` (``provision_mailbox``/``update_mailbox``/
    ``reset_mailbox_password``/``archive_mailbox``/``restore_mailbox``/
    ``delete_mailbox``) — not in this sub-task's brief; consistent with the
    Р2 decision already recorded in ``apps/mail/services/mailbox_service.py``
    (its module docstring: the actual Mailcow HTTP calls those actors made
    are deferred past this Django port; ``mailbox_service.py``'s own
    functions only flip the local row's status). ``final_purge_archived_mailboxes``
    below follows the same rule — it flips ``ProvisionedMailbox.status`` to
    ``"deleted"`` locally and does NOT call ``MailcowClient().delete_mailbox``.
  * ``services/notify_publish.py`` (Redis pub/sub notifications) — Р2,
    documented in ``apps/mail/services/sync/mapper.py``'s docstring already.
"""
from __future__ import annotations

import datetime
import logging

from celery import shared_task
from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.core.services import require_service
from apps.mail.models import (
    AuditLog,
    EmailAccount,
    EmailMessage,
    OAuthToken,
    ProvisionedMailbox,
    RecipientStatus,
)
from apps.mail.services import mail_config, reconcile_service
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import get_oauth_client
from apps.mail.services.sender.factory import get_sender
from apps.mail.services.sync import imap_sync

logger = logging.getLogger(__name__)


# ─── deliver_email (port of actors.py::deliver_email/_do_deliver) ──────────


@shared_task(max_retries=5)
def deliver_email(message_id: str) -> None:
    """Look up the message + account and dispatch to the right Sender.

    Port of ``actors.py::_do_deliver`` — the async SQLAlchemy session dance
    (``session.get``, explicit ``update(...)``/``commit()``) collapses to
    plain sync Django ORM calls, same observable transitions:

      * message/account missing → log + return (no retry, nothing to do).
      * account inactive → message folder stamped back to "outbox", THEN
        re-raise (so Dramatiq/Celery's retry/backoff applies — matches the
        source exactly).
      * success → every ``RecipientStatus`` row for the message → "sent",
        message folder → "sent" (+ provider ids if returned), best-effort
        reconcile sync enqueued.
      * failure → every ``RecipientStatus`` row → "bounced" with the sender's
        error, message folder back to "outbox", re-raise for retry.
    """
    require_service("mail")

    msg = EmailMessage.objects.filter(id=message_id).first()
    if msg is None:
        logger.warning("deliver_email_not_found message_id=%s", message_id)
        return
    if msg.account_id is None:
        logger.warning("deliver_email_no_account message_id=%s", message_id)
        return

    account = EmailAccount.objects.filter(id=msg.account_id).first()
    if account is None or not account.is_active:
        msg.folder = "outbox"
        msg.save(update_fields=["folder", "updated_at"])
        raise RuntimeError("account inactive")

    sender = get_sender(account.provider)
    result = sender.send(account, msg)

    RecipientStatus.objects.filter(message=msg).update(
        status="sent" if result.ok else "bounced",
        error_message=None if result.ok else result.error,
    )

    if result.ok:
        msg.folder = "sent"
        update_fields = ["folder", "updated_at"]
        if result.provider_message_id:
            msg.message_id = result.provider_message_id
            update_fields.append("message_id")
        if result.provider_thread_id:
            msg.thread_id = result.provider_thread_id
            update_fields.append("thread_id")
        msg.save(update_fields=update_fields)
        logger.info("delivered message_id=%s account_id=%s", msg.id, msg.account_id)
        # Reconcile Sent folder with provider state on next sync — best
        # effort, exactly like the source (swallows any enqueue failure).
        try:
            incremental_sync_account.delay(msg.account_id)
        except Exception:  # noqa: BLE001 — буквальный порт исходника
            pass
    else:
        msg.folder = "outbox"
        msg.save(update_fields=["folder", "updated_at"])
        logger.warning("deliver_failed message_id=%s err=%s", msg.id, result.error)
        raise RuntimeError(result.error)


# ─── incremental_sync_account (port of sync_actors.py) ─────────────────────
#
# Stable namespace for advisory locks — identical literal to the FastAPI
# original (``sync_actors.py::_ADVISORY_NAMESPACE``): keeps mail's locks
# separate from whatever else might use the same DB's advisory-lock space.
# ``pg_try_advisory_lock`` takes two 32-bit ints, first one is the namespace.
_ADVISORY_NAMESPACE = 0x454D4149  # 'EMAI'


def _try_advisory_lock(account_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, %s)", [_ADVISORY_NAMESPACE, account_id],
        )
        return bool(cursor.fetchone()[0])


def _advisory_unlock(account_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s, %s)", [_ADVISORY_NAMESPACE, account_id],
        )


@shared_task(max_retries=5)
def incremental_sync_account(account_id: int, hint_history_id: str | None = None) -> None:
    """Pull the delta since the last cursor for one ``EmailAccount``.

    Enqueued by the 3 webhook receivers (``apps/mail/webhooks.py``) and by
    ``imap_poll_fallback`` below. Preserves the FastAPI original's
    concurrency-control contract byte-for-byte: a non-blocking Postgres
    advisory lock keyed on ``account_id`` serialises concurrent runs (two
    webhook pushes racing, or a push racing a poll) — the loser observes the
    lock held and exits cleanly instead of double-syncing the same mailbox.

    Корпоративные ящики (``mailcow``/``imap``) синхронизируются по-настоящему
    — ``services/sync/imap_sync.py`` тянет письма и толкает обратно флаг
    ``\\Seen``. Раньше здесь был задокументированный no-op: живого
    IMAP-подключения в репозитории не существовало.

    Gmail/Graph по-прежнему seam: их драйверы (push-подписки, delta-link)
    остаются непортированными — это отдельная работа по OAuth-провайдерам, и
    к корпоративной почте она отношения не имеет.
    """
    require_service("mail")

    if not _try_advisory_lock(account_id):
        logger.info("sync_skipped_locked account=%s", account_id)
        return

    try:
        account = EmailAccount.objects.filter(id=account_id).first()
        if account is None:
            logger.warning("sync_account_missing account=%s", account_id)
            return
        if not account.is_active:
            logger.info("sync_skipped_inactive account=%s", account_id)
            return

        if account.provider in imap_sync.IMAP_PROVIDERS:
            imap_sync.sync_account_two_way(account)
            return

        logger.info(
            "sync_driver_not_ported account=%s provider=%s hint_history_id=%s",
            account_id, account.provider, hint_history_id,
        )
    finally:
        _advisory_unlock(account_id)


# ─── dlp_scan_attachment (port of actors.py::dlp_scan_attachment) ──────────


@shared_task(max_retries=3)
def dlp_scan_attachment(attachment_id: int) -> None:
    """Scan attachment for sensitive data.

    Literal port of the source's own stub — ``actors.py::dlp_scan_attachment``
    is itself just a log line + ``# TODO: real DLP scan logic`` (never wired
    from any router; ``apps/mail/services/attachment_service.py``'s docstring
    explains why: no live endpoint in the source ever uploads attachment
    bytes). Kept as a stub here for the same reason — there is no real logic
    upstream to port.
    """
    require_service("mail")
    logger.info("dlp_scanning_attachment attachment_id=%s", attachment_id)
    # TODO: real DLP scan logic (буквальный порт исходника — тот же TODO там же)


# ─── final_purge_archived_mailboxes (port of scheduler.py, ~03:15 UTC) ─────


@shared_task
def final_purge_archived_mailboxes() -> int:
    """Stage-2 of the user-delete cascade.

    Port of ``scheduler.py::final_purge_archived_mailboxes``: every
    ``ProvisionedMailbox`` whose status is ``"archived"`` and whose
    ``archived_at`` is older than ``MAILBOX_PURGE_AFTER_DAYS`` (getattr with
    the source's own default, 30 — ``htqweb/settings`` is out of this
    sub-task's zone) is marked ``"deleted"``.

    The source additionally enqueues ``mailbox_actors.py::delete_mailbox``
    (the actor that issues the real Mailcow hard-delete) — that actor is NOT
    ported in this sub-task (see module docstring: same Р2 decision already
    recorded by ``apps/mail/services/mailbox_service.py`` for create/archive/
    restore/delete, none of which call ``MailcowClient`` either). This task
    therefore performs the local status transition only.
    """
    require_service("mail")

    cutoff = timezone.now() - datetime.timedelta(
        days=getattr(settings, "MAILBOX_PURGE_AFTER_DAYS", 30),
    )
    rows = list(
        ProvisionedMailbox.objects.filter(status="archived", archived_at__lt=cutoff)
    )
    purged = 0
    for mb in rows:
        mb.status = "deleted"
        mb.deleted_at = timezone.now()
        mb.save(update_fields=["status", "deleted_at", "updated_at"])
        purged += 1

    if purged:
        logger.info("final_purge_archived_mailboxes purged=%d", purged)
    return purged


# ─── audit_log_compaction (port of scheduler.py, ~03:30 UTC) ───────────────


@shared_task
def audit_log_compaction() -> int:
    """Reap ``AuditLog`` (mail domain) rows past retention.

    Port of ``scheduler.py::audit_log_compaction`` — pure DB delete, no
    network involved, referenced by ``apps/mail/models.py::AuditLog``'s own
    docstring as the consumer that would eventually write/reap this table.
    """
    require_service("mail")

    cutoff = timezone.now() - datetime.timedelta(
        days=getattr(settings, "AUDIT_LOG_RETENTION_DAYS", 90),
    )
    deleted, _ = AuditLog.objects.filter(created_at__lt=cutoff).delete()
    if deleted:
        logger.info("audit_log_compaction_run deleted=%d", deleted)
    return deleted


# ─── imap_poll_fallback (port of scheduler.py, every 60s) ──────────────────


@shared_task
def imap_poll_fallback() -> int:
    """Catch-all poll for corporate accounts the push subscription missed.

    Port of ``scheduler.py::imap_poll_fallback``: picks corporate accounts
    whose ``last_sync_at`` is older than 2 minutes (or never synced) and
    enqueues ``incremental_sync_account`` for each — personal accounts are
    skipped, Pub/Sub/Graph webhooks own their delta.

    Отбор расширен с ``provider="mailcow"`` на оба IMAP-провайдера: у
    корпоративного сервера без Mailcow нет ни webhook'ов, ни push-подписок,
    поэтому этот опрос — его ЕДИНСТВЕННЫЙ источник новых писем, а не
    подстраховка.
    """
    require_service("mail")

    cutoff = timezone.now() - datetime.timedelta(minutes=2)
    ids = list(
        EmailAccount.objects.filter(provider__in=imap_sync.IMAP_PROVIDERS, is_active=True)
        .filter(Q(last_sync_at__isnull=True) | Q(last_sync_at__lt=cutoff))
        .values_list("id", flat=True)
    )
    if not ids:
        return 0
    for account_id in ids:
        incremental_sync_account.delay(account_id)
    logger.info("imap_poll_fallback enqueued=%d", len(ids))
    return len(ids)


# ─── reconcile_mailboxes (сверка платформы с почтовым сервером) ────────────


@shared_task
def reconcile_mailboxes() -> dict:
    """Периодическая двусторонняя сверка ящиков.

    По умолчанию (``MAIL_RECONCILE_AUTO_APPLY=false``) только СЧИТАЕТ
    расхождения и пишет их в лог — чтобы фоновая задача не заводила и не
    удаляла ящики без ведома админа. Применение делается руками из админки
    (``POST /api/email/v1/mailboxes/reconcile/``) или включается флагом, если
    команда осознанно хочет автосведение.

    Единственное исключение — привязка бесхозных ящиков к владельцам
    (``MAIL_RECONCILE_AUTO_LINK``, по умолчанию ВКЛЮЧЕНА). На почтовом сервере
    она ничего не меняет: у ящика не было владельца, а его адрес в точности
    совпал с email пользователя. Ради неё и заведён отдельный флаг — пока
    разрешение было общим, включить её можно было только вместе с
    автосозданием ящиков, и потому она не работала никогда.
    """
    require_service("mail")

    cfg = mail_config.get_config()
    auto_apply = bool(cfg.reconcile_auto_apply)
    auto_link = bool(cfg.reconcile_auto_link)
    report = reconcile_service.reconcile(
        apply=auto_apply, direction="both" if auto_apply else "report",
        link_orphans=auto_link,
    )
    if report.differences:
        logger.warning(
            "mail_reconcile_differences mode=%s only_local=%d only_remote=%d "
            "mismatched=%d unlinked=%d linked=%d applied=%s auto_link=%s",
            report.mode,
            sum(1 for d in report.differences if d.kind == "only_local"),
            sum(1 for d in report.differences if d.kind == "only_remote"),
            sum(1 for d in report.differences if d.kind == "mismatched"),
            # unlinked — ящики, у которых нашёлся владелец по адресу; linked —
            # сколько из них реально привязано (только при auto_apply).
            sum(1 for d in report.differences if d.kind == "unlinked"),
            sum(1 for d in report.differences if d.action == "linked"),
            auto_apply,
            auto_link,
        )
    return report.to_dict()


# ─── oauth_token_refresh (port of scheduler.py, every 5 min) ───────────────


@shared_task
def oauth_token_refresh() -> int:
    """Refresh ``OAuthToken`` rows that expire in the next 15 minutes.

    Port of ``scheduler.py::oauth_token_refresh`` — per-token refresh
    failures are logged and skipped (best effort, matches the source), the
    loop keeps going for the rest of the batch.
    """
    require_service("mail")

    threshold = timezone.now() + datetime.timedelta(minutes=15)
    tokens = list(
        OAuthToken.objects.filter(
            is_active=True,
            expires_at__lte=threshold,
            encrypted_refresh_token__isnull=False,
        )
    )

    refreshed = 0
    for token in tokens:
        try:
            client = get_oauth_client(token.provider)
            refresh = crypto_service.decrypt(token.encrypted_refresh_token)
            bundle = client.refresh(refresh)
            token.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
            if bundle.refresh_token:
                token.encrypted_refresh_token = crypto_service.encrypt(bundle.refresh_token)
            token.expires_at = timezone.now() + datetime.timedelta(seconds=bundle.expires_in)
            token.save(update_fields=[
                "encrypted_access_token", "encrypted_refresh_token", "expires_at", "updated_at",
            ])
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
            logger.warning("oauth_refresh_failed token=%s: %s", token.id, exc)

    if refreshed:
        logger.info("oauth_token_refresh refreshed=%d", refreshed)
    return refreshed
