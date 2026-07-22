"""``manage.py run_imap_idle`` — documented stub for the IMAP IDLE supervisor.

Port target: ``services/email/app/workers/imap_idle_supervisor.py`` — its own
long-running process (NOT a Celery task; a Celery worker pool isn't the
right home for N permanently-open ``asyncio`` IMAP IDLE sessions), started
in the source with ``python -m app.workers.imap_idle_supervisor``. Here the
equivalent entry point is ``python manage.py run_imap_idle``.

NOT implemented in this sub-task (webhooks+workers, PLAN.md §6.4) — scoped
out deliberately, not an oversight:

* The supervisor's core loop (``Supervisor.add``/``_idle_loop``) opens a real
  ``aioimaplib`` IMAP connection per corporate (Mailcow) account and blocks
  on IDLE, which needs a reachable Mailcow IMAP host — there is none in this
  repo/CI (Р3: "mailcow/провайдеры — seam без живой сети").
* Its add/drop signalling (``Supervisor.listen_for_changes``) is a Redis
  pub/sub subscriber on channel ``email.account.changed`` — Redis pub/sub is
  explicitly NOT portable to this Django monolith (Р2, same decision as
  ``services/notify_publish.py`` and ``workers/user_events.py``, see
  ``apps/mail/tasks.py``'s module docstring and ``apps/mail/interface.py``).

Both blockers are exactly the ones the sub-task brief anticipated
("ЕСЛИ слишком объёмно — оставь заглушку-команду с TODO и задокументируй
(не блокируй домен)") — this command is that documented stub. A future
sub-task that actually stands up a reachable Mailcow IMAP endpoint should
port ``_resolve_account_creds``/``_idle_loop``/``Supervisor`` here, replacing
the Redis-pub/sub add/drop mechanism with a plain DB re-poll (the same
substitution already made for ``workers/user_events.py`` →
``apps.mail.interface.archive_user_mailboxes``: a direct call/poll instead of
pub/sub).

Safe to invoke today: logs and returns immediately (does not busy-loop, does
not raise) — same fail-safe shape as the source's own
``main()`` when ``MAILCOW_API_URL`` is unset ("stays up without
busy-restarting").
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services import require_service


class Command(BaseCommand):
    help = (
        "IMAP IDLE supervisor for corporate (Mailcow) mailboxes — NOT YET "
        "IMPLEMENTED (documented stub, see module docstring for why). "
        "Port target: services/email/app/workers/imap_idle_supervisor.py."
    )

    def handle(self, *args, **options):
        require_service("mail")
        self.stdout.write(self.style.WARNING(
            "run_imap_idle: stub — the IMAP IDLE supervisor is not ported "
            "(needs a live Mailcow IMAP host + a Redis pub/sub add/drop "
            "channel that this Django monolith doesn't carry forward, see "
            "apps/mail/management/commands/run_imap_idle.py's module "
            "docstring). Corporate mailboxes fall back to "
            "apps.mail.tasks.imap_poll_fallback (60s poll) in the meantime."
        ))
