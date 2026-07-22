"""Публичный API аппки mail для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза mail, PLAN.md §6.4 — под-задача webhooks+
workers, последняя в домене mail). Потребитель: apps.users — каскад
деактивации пользователя (SUSPENDED → архивация почтовых ящиков). Вызов из
users добавляется на интеграции (PLAN.md §8, call-site в apps.users НЕ
трогается здесь). Прямой импорт apps.mail.* из другой аппки запрещён
(test_app_isolation.py) — это единственная разрешённая дверь.

Реализация — порт каскада ``services/email/app/workers/user_events.py``
(``CHANNEL_DEACTIVATED`` ветка ``_handle``): та функция подписывалась на
Redis pub/sub канал ``user.deactivated``, публикуемый user-service. Redis
pub/sub НЕ портируется в этот Django-монолит (Р2 — тот же класс решений, что
и ``notify_publish``/``sync/mapper.py``'s docstring) — эта interface-функция
СТАЛА подписчиком: users вызывает её напрямую (обычный Python-вызов вместо
pub/sub), тот же наблюдаемый эффект.

Функция начинается с require_service("mail").
"""
from __future__ import annotations

from apps.core.services import require_service
from apps.mail.models import AccountType, EmailAccount, ProvisionedMailbox
from apps.mail.services import mailbox_service as mbx_svc


def archive_user_mailboxes(user_id: int) -> None:
    """Archive every mailbox owned by ``user_id`` (personal + corporate).

    Port of ``user_events.py``'s ``_archive_personal_accounts`` +
    ``_archive_corporate_mailbox`` (``CHANNEL_DEACTIVATED`` path only — the
    30-day purge-clock stamping done on ``CHANNEL_DELETED`` is a distinct
    lifecycle event, not part of this interface function's contract, and
    ``final_purge_archived_mailboxes`` (``apps/mail/tasks.py``) already reaps
    anything archived past ``MAILBOX_PURGE_AFTER_DAYS`` regardless of how it
    got archived).

    * Personal (OAuth) ``EmailAccount`` rows → ``is_active=False`` (pauses
      their sync; the row is kept so re-activation is one PATCH away, same
      as the source).
    * The corporate ``ProvisionedMailbox`` (at most one per ``user_id`` —
      ``unique=True`` on that column) → archived via
      ``mailbox_service.archive()`` (already-tested local status transition;
      does NOT call ``MailcowClient`` — Р2/seam, see that module's
      docstring). ``CannotArchive`` is swallowed: a mailbox that is already
      ``archived``/``deleted``/``error`` needs no action here, mirroring the
      source's ``status == "active"`` filter (nothing to do outside that
      state).
    """
    require_service("mail")

    EmailAccount.objects.filter(
        user_id=user_id, type=AccountType.PERSONAL, is_active=True,
    ).update(is_active=False)

    mb = ProvisionedMailbox.objects.filter(user_id=user_id, status="active").first()
    if mb is not None:
        try:
            mbx_svc.archive(mb.id)
        except mbx_svc.CannotArchive:
            pass
