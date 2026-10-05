"""Перенести старую ленту колокольчика (``tasks.Notification`` в схеме
компании) в центр уведомлений (A1.5 модуля БЗО).

Запускается по разу на каждую компанию во время выкатки, ДО того как
контракт-миграция удалит ``tasks.Notification``. Идемпотентна: у перенесённой
строки ``event = "legacy.tasks.<старый id>"`` в пределах компании — повтор
её пропускает. Дата создания и прочтение сохраняются; письма и Telegram не
рассылаются — это история, а не новые события. Строка со старым FK на задачу
без ``target_type`` становится целью ``task``. Старые строки читаются через
``apps.tasks.interface.legacy_notifications`` — межаппный импорт моделей
запрещён.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.notifications.models import Notification
from apps.tasks import interface as tasks
from htqweb.tenancy.db import use_company

LEGACY_PREFIX = "legacy.tasks."


class Command(BaseCommand):
    help = "Перенести ленту колокольчика компании из tasks в центр уведомлений."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)

    def handle(self, *args, company, **options):
        with use_company(company):
            old_rows = tasks.legacy_notifications()
        done = set(Notification.objects.filter(
            company_slug=company, event__startswith=LEGACY_PREFIX,
        ).values_list("event", flat=True))
        fresh = []
        for old in old_rows:
            event = f"{LEGACY_PREFIX}{old['id']}"
            if event in done:
                continue
            target_type = old["target_type"] or ("task" if old["task_id"] else "")
            target_id = old["target_id"] if old["target_id"] is not None else old["task_id"]
            fresh.append((old, Notification(
                recipient_id=old["recipient_id"], company_slug=company, event=event,
                title=old["verb"][:255], target_type=target_type,
                target_id=str(target_id) if target_id is not None else "",
                actor_id=old["actor_id"], actor_avatar_url=old["actor_avatar_url"],
                is_read=old["is_read"], read_at=old["read_at"])))
        with transaction.atomic():
            created = Notification.objects.bulk_create([row for _, row in fresh],
                                                       batch_size=1000)
            # auto_now_add перезаписал дату при вставке — вернуть исходную.
            for (old, _), row in zip(fresh, created):
                row.created_at = old["created_at"]
            Notification.objects.bulk_update(created, ["created_at"], batch_size=1000)
        self.stdout.write(self.style.SUCCESS(
            f"Перенесено уведомлений: {len(created)} (уже было: {len(old_rows) - len(fresh)})"))
