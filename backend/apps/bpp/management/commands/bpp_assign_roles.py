"""Выдать должностям управляющей компании роли модуля БЗО (мастер-план §2.4).

Идемпотентна: уже выданную роль не трогает. Должности, которых нет в
компании, перечисляет в выводе. ``bpp-adm`` выдаётся лично, не должности.
"""

from django.core.management.base import BaseCommand

from apps.access import interface as access
from apps.hr import interface as hr
from htqweb.tenancy.db import use_company

POSITION_ROLES = {
    "Финансовый директор": "bpp-fd",
    "Технический директор": "bpp-td",
    "Операционный директор": "bpp-od",
    "Генеральный директор": "bpp-gd",
    "Главный бухгалтер": "bpp-buh",
    "Бухгалтер": "bpp-buh",
    "Менеджер по закупкам": "bpp-sn",
    "Руководитель проекта": "bpp-pm",
}


class Command(BaseCommand):
    help = "Выдать должностям компании роли модуля БЗО."

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
