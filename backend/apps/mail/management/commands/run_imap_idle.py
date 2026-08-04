"""``manage.py run_imap_idle`` — documented stub for the IMAP IDLE supervisor.

Port target: ``services/email/app/workers/imap_idle_supervisor.py`` — its own
long-running process (NOT a Celery task; a Celery worker pool isn't the
right home for N permanently-open ``asyncio`` IMAP IDLE sessions), started
in the source with ``python -m app.workers.imap_idle_supervisor``. Here the
equivalent entry point is ``python manage.py run_imap_idle``.

СТАТУС: заглушка, но причина уже другая, чем была.

Изначально команда не была реализована по двум причинам: (1) не существовало
живого IMAP-подключения и достижимого почтового хоста, (2) сигнализация
add/drop у исходника шла через Redis pub/sub, который в этот Django-монолит
не переносится.

Первая причина снята: ``apps/mail/services/imap_client.py`` даёт живое
соединение, ``apps/mail/services/sync/imap_sync.py`` — полноценную
двустороннюю синхронизацию, и корпоративная почта РАБОТАЕТ — через
``apps.mail.tasks.imap_poll_fallback`` (опрос раз в 60 секунд, зарегистрирован
периодической задачей в миграции ``0004_mail_periodic_tasks``). То есть письма
приходят и уходят без этой команды; IDLE дал бы только меньшую задержку
(секунды вместо ≤60) ценой N постоянно открытых соединений и отдельного
процесса в docker-compose.

Что осталось сделать, если задержка в минуту окажется неприемлемой: поднять
здесь по потоку на активный корпоративный ``EmailAccount``, держать
``IMAP IDLE`` и на каждое уведомление звать
``imap_sync.sync_account_two_way``; вместо Redis-pub/sub add/drop —
перечитывать список аккаунтов из БД раз в N секунд (та же замена, что уже
сделана для ``workers/user_events.py`` → ``apps.mail.interface``).

Безопасно вызывать сегодня: печатает пояснение и выходит (не крутит цикл, не
падает).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services import require_service


class Command(BaseCommand):
    help = (
        "IMAP IDLE supervisor for corporate mailboxes — NOT IMPLEMENTED "
        "(documented stub). Corporate mail already works via the 60s poll "
        "apps.mail.tasks.imap_poll_fallback; IDLE would only cut the latency. "
        "See the module docstring."
    )

    def handle(self, *args, **options):
        require_service("mail")
        self.stdout.write(self.style.WARNING(
            "run_imap_idle: заглушка — супервизор IMAP IDLE не реализован.\n"
            "Корпоративная почта при этом РАБОТАЕТ: синхронизацию выполняет "
            "периодическая задача apps.mail.tasks.imap_poll_fallback (опрос "
            "раз в 60 секунд, включена миграцией 0004). IDLE сократил бы "
            "задержку до секунд — см. модульный докстринг этой команды."
        ))
