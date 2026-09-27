"""Снять шаблон «Заявка на закуп» (модуль БЗО, задача B6.3, D-10, Q-A04).

Закупка теперь — типизированная заявка модуля БЗО (``bpp.purchase_request``),
шаблон конструктора форм ей больше не нужен. Команда:

- отзывает идущие согласования заявок этого шаблона — в ``public`` и в
  схеме каждой действующей компании (``signoff`` — тенантная аппка);
- удаляет сами заявки: это тестовые заявки пилота (Q-A04);
- переводит шаблон в «удалён» (``TemplateStatus.DELETED``) — форма скрыта и
  не подаётся, но его таблица данных остаётся;
- справочники форм (``RequestReferenceSource``) не трогает вовсе.

Идемпотентна: повторный запуск по уже снятому шаблону ничего не меняет.
``--dry-run`` — только сводка.

    manage.py retire_purchase_request_template [--slug zayavka-na-zakup] [--dry-run]
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.approvals.models import (
    RequestFormTemplate,
    RequestInstance,
    RequestReferenceSource,
    TemplateStatus,
)
from apps.companies import interface as companies
from apps.signoff import interface as signoff
from htqweb.tenancy.db import use_company

from .seed_purchase_request_template import DEFAULT_SLUG

SUBJECT = RequestInstance.SIGNOFF_SUBJECT_TYPE


class Command(BaseCommand):
    help = "Снять шаблон «Заявка на закуп»: форма скрыта, заявки удалены, справочники целы."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=DEFAULT_SLUG)
        parser.add_argument("--dry-run", action="store_true")

    def _cancel_processes(self, instance_ids: list[int]) -> int:
        cancelled = 0
        for slug in [None, *companies.active_company_slugs()]:
            if slug is None:
                cancelled += self._cancel_here(instance_ids)
                continue
            with use_company(slug):
                cancelled += self._cancel_here(instance_ids)
        return cancelled

    @staticmethod
    def _cancel_here(instance_ids: list[int]) -> int:
        cancelled = 0
        for instance_id in instance_ids:
            process = signoff.get_process_for(SUBJECT, instance_id)
            if process is not None and process["state"] == "pending":
                signoff.cancel_process(process_id=process["id"])
                cancelled += 1
        return cancelled

    def handle(self, *args, slug: str, dry_run: bool, **options):
        templates = list(RequestFormTemplate.objects.filter(slug=slug))
        if not templates:
            self.stdout.write(f"шаблона со slug «{slug}» нет — снимать нечего")
            return
        for template in templates:
            instance_ids = list(template.instances.values_list("pk", flat=True))
            sources = RequestReferenceSource.objects.filter(template_id=template.pk).count()
            already = template.status == TemplateStatus.DELETED and not instance_ids
            self.stdout.write(
                f"шаблон [{template.pk}] «{template.name}»: статус {template.status}, "
                f"заявок {len(instance_ids)}, таблиц данных {sources}")
            if dry_run or already:
                if already:
                    self.stdout.write("  уже снят — без изменений")
                continue
            with transaction.atomic():
                cancelled = self._cancel_processes(instance_ids)
                RequestInstance.objects.filter(pk__in=instance_ids).delete()
                template.status = TemplateStatus.DELETED
                template.is_active = False
                template.save(update_fields=["status", "is_active", "updated_at"])
            self.stdout.write(self.style.SUCCESS(
                f"  снят: отозвано согласований {cancelled}, удалено заявок "
                f"{len(instance_ids)}, таблица данных и справочники сохранены"))
