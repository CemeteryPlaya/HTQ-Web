"""Выдать должностям компании роли тендерного модуля (T0.3; план этапов 0–2, §1).

Образец — ``bpp_assign_roles``. Идемпотентна: уже выданную роль не трогает.
Должности, которых нет в компании, перечисляет в выводе. ``tender-adm``
выдаётся лично, не должности.

Закупщику для отправки заявки нужны ещё роли БЗО (``bpp-sn``/``bpp-pm``):
заявки на закупку в БЗО подаются от его имени — их выдаёт ``bpp_assign_roles``.
"""

from django.core.management.base import BaseCommand

from apps.access import interface as access
from apps.hr import interface as hr
from htqweb.tenancy.db import use_company

POSITION_ROLES = {
    "Менеджер по закупкам": "tender-buyer",
    "Руководитель проекта": "tender-buyer",
    "Технический директор": "tender-quality",
    "Финансовый директор": "tender-fd",
    "Главный бухгалтер": "tender-viewer",
    "Бухгалтер": "tender-viewer",
    "Операционный директор": "tender-viewer",
}


class Command(BaseCommand):
    help = "Выдать должностям компании роли тендерного модуля."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, dry_run, **options):
        with use_company(company):
            positions = hr.positions_by_title(list(POSITION_ROLES))
        for title, role in POSITION_ROLES.items():
            position_id = positions.get(title)
            if position_id is None:
                self.stdout.write(f"нет должности: {title}")
                continue
            if dry_run:
                self.stdout.write(f"выдать {role} → {title} (#{position_id})")
                continue
            created = access.ensure_position_role(company, position_id, role, "company")
            self.stdout.write(f"{'выдано' if created else 'уже есть'}: {role} → {title}")
