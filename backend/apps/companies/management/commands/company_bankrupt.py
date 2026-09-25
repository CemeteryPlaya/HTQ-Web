"""Закрыть компанию с преемником: членства → преемник, компания → архив.

Тонкая обёртка над ``apps.companies.services.lifecycle.bankrupt_company`` —
та же операция, что кнопка «Банкротство…» в реестре компаний. Спека:
docs/plans/2026-09-26-company-bankruptcy-spec.md. Сначала ``--dry-run``:
сводка показывает, сколько людей получат доступ к преемнику.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = ("Банкротство компании: участники получают членство в преемнике, "
            "компания уходит в архив (только чтение).")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug закрываемой компании")
        parser.add_argument("--successor", required=True, help="slug компании-преемника")
        parser.add_argument("--dry-run", action="store_true",
                            help="только посчитать, ничего не менять")

    def handle(self, *args, **opts):
        try:
            result = lifecycle.bankrupt_company(
                opts["company"], opts["successor"], dry_run=opts["dry_run"])
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        summary = (f"Участников с действующей учёткой: {result.members_total}; "
                   f"получат доступ к {result.successor.slug}: {result.members_granted}; "
                   f"уже состоят: {result.members_already}.")
        if result.dry_run:
            self.stdout.write(f"Сухой прогон. {summary} Ничего не изменено.")
            return
        tail = ("Компания переведена в архив." if result.archived
                else "Компания уже была в архиве.")
        self.stdout.write(self.style.SUCCESS(
            f"{summary} Преемник {result.company.slug} → {result.successor.slug}. {tail}"))
