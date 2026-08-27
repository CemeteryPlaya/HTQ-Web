"""``manage.py mail_check`` — диагностика подключения к корпоративной почте.

Зачем отдельная команда: при настройке по IMAP через SSH-туннель в цепочке
четыре звена (настройки → туннель → IMAP → SMTP), и любое может отвалиться.
Без неё единственный способ проверить — попытаться завести ящик в админке и
гадать по тексту ошибки, что именно не так.

Вторая цепочка — Mailcow API (адрес → хост → ключ → домен → ящики). Она нужна
в тот единственный день, когда ключ вписывают впервые: самая частая причина
«ключ есть, а не работает» — список разрешённых IP в Mailcow, и увидеть это
иначе неоткуда. В режиме IMAP цепочка сворачивается в один пропуск.

Сама логика проверок живёт в ``apps/mail/services/connection_check.py`` —
её же использует кнопка «Проверить» на странице «Корпоративные ящики».
Команда здесь только печатает отчёт: два расходящихся диагноста никому не
нужны.

Примеры::

    # что настроено и жив ли туннель — секретов не требует
    manage.py mail_check

    # полная проверка ящика: IMAP-вход, папки, SMTP-вход
    manage.py mail_check --mailbox i.ivanov@htq.group --password 'S3cret!'

    # то же, но пароль берётся из БД (для уже заведённого ящика)
    manage.py mail_check --mailbox i.ivanov@htq.group

    # плюс реальная отправка письма
    manage.py mail_check --mailbox i.ivanov@htq.group --send-to me@example.com

Пароль не печатается никогда, в том числе в сообщениях об ошибках.
Код возврата 1 при любом провале — команду можно ставить в скрипт.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import connection_check
from apps.mail.services.crypto import crypto_service

MARK = {
    connection_check.OK: "  [ ok ]",
    connection_check.FAIL: "  [FAIL]",
    connection_check.SKIP: "  [ -- ]",
}


class Command(BaseCommand):
    help = (
        "Проверить подключение к корпоративному почтовому серверу: настройки, "
        "Mailcow API, доступность туннеля, IMAP-вход, папки, SMTP. "
        "Секреты не печатает."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mailbox",
            help="Адрес ящика для проверки входа. Без него проверяются только "
                 "настройки и доступность портов.",
        )
        parser.add_argument(
            "--password",
            help="Пароль ящика. Если не задан — берётся сохранённый в БД "
                 "(ProvisionedMailbox.encrypted_smtp_app_password).",
        )
        parser.add_argument(
            "--send-to",
            help="Отправить тестовое письмо на этот адрес (реальная отправка!).",
        )
        parser.add_argument(
            "--timeout", type=int, default=10,
            help="Таймаут сетевых проверок, секунд (по умолчанию 10).",
        )

    def handle(self, *args, **options):
        mailbox = options.get("mailbox")
        password = options.get("password") or self._stored_password(mailbox)

        report = connection_check.run_check(
            mailbox=mailbox, password=password,
            send_to=options.get("send_to"), timeout=options["timeout"],
        )

        for step in report.steps:
            line = f"{MARK[step.status]} {step.title}: {step.detail}"
            if step.status == connection_check.OK:
                self.stdout.write(self.style.SUCCESS(line))
            elif step.status == connection_check.FAIL:
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(line)

            for hint_line in (step.hint or "").splitlines():
                self.stdout.write(f"         → {hint_line}")
            self._print_extras(step)

        self.stdout.write("")
        if not report.ok:
            raise CommandError("Проверка не пройдена — см. отметки [FAIL] выше.")
        self.stdout.write(self.style.SUCCESS("Все проверки пройдены."))

    def _print_extras(self, step) -> None:
        """Подробности, которые полезно видеть глазами: список папок сервера и
        счётчики писем. В JSON-отчёт для UI они уходят через ``step.data``."""
        available = step.data.get("available")
        if available:
            shown = ", ".join(available[:12]) + ("…" if len(available) > 12 else "")
            self.stdout.write(f"         папки на сервере: {shown}")
        for folder, stats in (step.data.get("counts") or {}).items():
            self.stdout.write(
                f"         {folder}: писем {stats['messages']}, "
                f"uidvalidity={stats['uidvalidity']}"
            )

    @staticmethod
    def _stored_password(address: str | None) -> str | None:
        """Пароль уже заведённого ящика — чтобы не вводить его руками."""
        if not address:
            return None
        mb = ProvisionedMailbox.objects.filter(address=address).first()
        if mb is None or not mb.encrypted_smtp_app_password:
            return None
        try:
            return crypto_service.decrypt(mb.encrypted_smtp_app_password)
        except Exception:  # noqa: BLE001 — сообщит сама проверка: «нет пароля»
            return None
