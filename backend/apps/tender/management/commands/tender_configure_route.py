"""Маршрут утверждения выбора поставщиков ``tender.award`` (T5.2; T-11).

    manage.py tender_configure_route --company <slug> [--fd ID | --fd <компания>:<id>] [--dry-run]

Два этапа: «Проверка качества» — исполнителя называет тендер (назначенный
проверяющий с ролью ``tender-quality``, иначе держатели должности
«Технический директор», ``approval_hooks``), «Утверждение ФД» — должность
«Финансовый директор» своей компании, а если её нет — ближайшей вышестоящей
(директора — в штате холдинга, B8.1). Этапа ГД в пилоте нет (T-11).

Флаги — как у маршрутов БЗО: автор не утверждает свой выбор, комментарий к
возврату и отказу — не короче 10 символов, исполнители — на момент этапа.
Идемпотентна: активный маршрут не трогает (заменить — деактивировать старый
на странице маршрута).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.companies import interface as companies
from apps.hr import interface as hr
from apps.signoff import interface as signoff
from htqweb.tenancy.db import use_company

SUBJECT = "tender.award"
FD_TITLE = "Финансовый директор"
COMMENT_MIN = 10


def _ref(company: str, position_id: int) -> dict:
    return {"company": company, "position_id": int(position_id)}


class Command(BaseCommand):
    help = "Маршрут утверждения выбора поставщиков тендера: проверка качества → ФД"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        parser.add_argument("--fd", default=None,
                            help="должность ФД: id своей компании или <компания>:<id> "
                                 "вышестоящей (по умолчанию — по названию)")
        parser.add_argument("--dry-run", action="store_true")

    def _fd(self, company: str, value: str | None) -> dict | None:
        if value:
            owner, _, position_id = value.rpartition(":")
            try:
                return _ref("" if owner in ("", company) else owner, int(position_id))
            except ValueError as exc:
                raise CommandError(f"Должность «{value}»: ожидается id или "
                                   f"<компания>:<id>") from exc
        found = hr.positions_by_title([FD_TITLE]).get(FD_TITLE)
        if found:
            return _ref("", found)
        for upper in companies.ancestor_slugs(company):
            with use_company(upper):
                found = hr.positions_by_title([FD_TITLE]).get(FD_TITLE)
            if found:
                return _ref(upper, found)
        return None

    def handle(self, *args, company, fd, dry_run, **options):
        if companies.get_company(company) is None or not companies.schema_exists(company):
            raise CommandError(f"Компании «{company}» нет или у неё нет схемы — сначала "
                               f"company_create / migrate_companies.")
        with use_company(company):
            if signoff.has_active_route(SUBJECT):
                self.stdout.write("уже есть: активный маршрут выбора поставщиков — не менялся")
                return
            position = self._fd(company, fd)
            if position is None:
                raise CommandError(f"Нет должности «{FD_TITLE}» ни в компании, ни выше по "
                                   f"дереву — заведите её или передайте --fd.")
            where = (f"#{position['position_id']}" if not position["company"]
                     else f"{position['company']}:#{position['position_id']}")
            stages = [
                {"order": 1, "name": "Проверка качества", "quorum": "any",
                 "approver_kind": "subject", "approver_key": "quality_reviewer"},
                {"order": 2, "name": "Утверждение ФД", "quorum": "any",
                 "positions": [position]},
            ]
            flags = {"forbid_self_approval": True, "reject_comment_min": COMMENT_MIN,
                     "lazy_resolution": True}
            if dry_run:
                self.stdout.write(f"завести маршрут: Проверка качества → ФД {where}, "
                                  f"флаги {flags}")
                return
            try:
                route_id = signoff.configure_route(subject_type=SUBJECT,
                                                   name="Выбор поставщиков: качество → ФД",
                                                   stages=stages, flags=flags)
            except signoff.RouteConflict as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"заведён маршрут выбора поставщиков #{route_id}: "
                              f"Проверка качества → ФД {where}")
