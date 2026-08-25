"""Разовая сверка кадровой копии идентичности с аккаунтами.

Первый прогон на живых данных приведёт копии в соответствие с аккаунтами и
оформит каждое найденное кадровое значение заявкой — ничего не теряется, но
очередь подтверждающего разом получит всё, что накопилось за время, пока
синка не существовало вовсе. Поэтому ``--dry-run`` показывает объём заранее, а
``--department`` позволяет пройти отделами, а не всей базой сразу.

Спека: docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §13.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.hr.models import Employee, EmployeeStatus
from apps.hr.services import identity_sync_service


class Command(BaseCommand):
    help = "Сверить кадровые копии идентичности с аккаунтами платформы"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="только показать расхождения, ничего не писать",
        )
        parser.add_argument("--limit", type=int, default=None,
                            help="обработать не больше N сотрудников")
        parser.add_argument("--department", type=int, default=None,
                            help="ограничиться одним отделом (id)")

    def handle(self, *args, **options):
        queryset = (Employee.objects
                    .filter(is_deleted=False, user_id__isnull=False)
                    .exclude(status=EmployeeStatus.TERMINATED)
                    .order_by("id"))
        if options["department"]:
            queryset = queryset.filter(department_id=options["department"])

        employees = list(queryset[:options["limit"]] if options["limit"] else queryset)
        drifted = 0

        for employee in employees:
            snapshot = identity_sync_service.account_snapshot(employee.user_id)
            if snapshot is None:
                self.stdout.write(
                    f"  ! сотрудник {employee.id}: аккаунт {employee.user_id} недоступен"
                )
                continue

            fields = identity_sync_service.diff_against_account(employee, snapshot)
            if not fields:
                continue

            drifted += 1
            self.stdout.write(
                f"  ~ сотрудник {employee.id} ({employee.last_name} "
                f"{employee.first_name}): {', '.join(fields)}"
            )
            if not options["dry_run"]:
                identity_sync_service.reconcile_employee(employee.id)

        verb = "нашлось" if options["dry_run"] else "обработано"
        self.stdout.write(self.style.SUCCESS(
            f"Проверено {len(employees)}, {verb} расхождений: {drifted}"
        ))
        if options["dry_run"] and drifted:
            self.stdout.write(
                "Прогон без --dry-run заведёт столько же заявок подтверждающему."
            )
