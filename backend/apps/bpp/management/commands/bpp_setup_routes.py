"""Завести маршруты согласования документов модуля БЗО (ТЗ §16.1, D-21).

Сейчас — заявка на закупку: «ТД → ОД», по должностям управляющей компании.
Маршрут заводится с флагами БЗО:

- запрет самосогласования, эскалация на ГД, уведомление ФД, если автор —
  сам ГД (BR-061, D-22);
- комментарий к отказу и возврату — не короче 10 символов (BR-060);
- ленивое разрешение исполнителей и «Нет исполнителя» с уведомлением ГД
  (ТЗ §16.1 п.2, п.5).

Должности ищутся по названию (``hr.positions_by_title``), явные
``--td``/``--od``/``--gd``/``--fd`` их перебивают. Идемпотентна: активный
маршрут типа не трогает — чтобы заменить его, деактивируйте старый на
странице маршрута.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.hr import interface as hr
from apps.signoff import interface as signoff
from htqweb.tenancy.db import use_company

REQUEST = "bpp.purchase_request"
TITLES = {
    "td": "Технический директор",
    "od": "Операционный директор",
    "gd": "Генеральный директор",
    "fd": "Финансовый директор",
}
COMMENT_MIN = 10


class Command(BaseCommand):
    help = "Завести маршруты согласования модуля БЗО (заявка: ТД → ОД) с флагами БЗО."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        for key, title in TITLES.items():
            parser.add_argument(f"--{key}", type=int, default=None,
                                help=f"id должности «{title}» (по умолчанию — по названию)")
        parser.add_argument("--dry-run", action="store_true")

    def _positions(self, options) -> dict[str, int | None]:
        found = hr.positions_by_title(list(TITLES.values()))
        return {key: options.get(key) or found.get(title) for key, title in TITLES.items()}

    def handle(self, *args, company, dry_run, **options):
        with use_company(company):
            positions = self._positions(options)
            missing = [TITLES[key] for key in ("td", "od") if not positions[key]]
            if missing:
                raise CommandError(
                    f"Нет должностей: {', '.join(missing)} — заведите их в структуре или "
                    f"передайте --td/--od.")
            for key in ("gd", "fd"):
                if not positions[key]:
                    self.stdout.write(f"нет должности «{TITLES[key]}» — "
                                      f"{'эскалация' if key == 'gd' else 'уведомление'} "
                                      f"не настроено")
            if signoff.has_active_route(REQUEST):
                self.stdout.write("уже есть: активный маршрут заявки на закупку — не менялся")
                return
            flags = {
                "forbid_self_approval": True,
                "reject_comment_min": COMMENT_MIN,
                "lazy_resolution": True,
                "escalation_position_id": positions["gd"],
                "no_executor_notify_position_ids": [p for p in (positions["gd"],) if p],
                "self_skip_notify_position_ids": [p for p in (positions["fd"],) if p],
            }
            stages = [
                {"order": 1, "name": "Технический директор", "quorum": "any",
                 "position_ids": [positions["td"]]},
                {"order": 2, "name": "Операционный директор", "quorum": "any",
                 "position_ids": [positions["od"]]},
            ]
            if dry_run:
                self.stdout.write(f"завести маршрут заявки: ТД #{positions['td']} → "
                                  f"ОД #{positions['od']}, флаги {flags}")
                return
            try:
                route_id = signoff.configure_route(
                    subject_type=REQUEST, name="Заявка на закупку: ТД → ОД", stages=stages,
                    flags=flags)
            except signoff.RouteConflict as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(f"заведён маршрут заявки на закупку #{route_id}")
