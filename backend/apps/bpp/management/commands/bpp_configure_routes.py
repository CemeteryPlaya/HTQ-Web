"""Завести маршруты согласования документов модуля БЗО (ТЗ §16.1, D-21).

По должностям управляющей компании, с флагами БЗО:

- **заявка на закупку** — «ТД → ОД»;
- **договор** — «ФД → ТД → ОД → ГД» (BR-035);
- **допсоглашение** (область ``supplementary``, D-18) — этап ФД только при
  росте суммы (``amount_delta > 0``); без изменения суммы этапов не остаётся
  и допсоглашение вступает в силу сразу (флаг ``skip_unmatched_groups``);
- **счёт на оплату** — один этап ФД (D-12) с требованием ``bpp:budget``:
  «Согласовать» из общего инбокса проходит проверку бюджета, как «Оплатить».

Флаги у всех маршрутов:

- запрет самосогласования, эскалация на ГД, уведомление ФД, если автор —
  сам ГД (BR-061, D-22);
- комментарий к отказу и возврату — не короче 10 символов (BR-060);
- ленивое разрешение исполнителей и «Нет исполнителя» с уведомлением ГД
  (ТЗ §16.1 п.2, п.5).

Должности ищутся по названию (``hr.positions_by_title``), явные
``--td``/``--od``/``--gd``/``--fd`` их перебивают. Идемпотентна: активный
маршрут типа и области не трогает — чтобы заменить его, деактивируйте
старый на странице маршрута. Маршруты договора требуют всех четырёх
должностей; без ФД или ГД заводится только маршрут заявки.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.hr import interface as hr
from apps.signoff import interface as signoff
from htqweb.tenancy.db import use_company

REQUEST = "bpp.purchase_request"
AGREEMENT = "bpp.agreement"
INVOICE = "bpp.invoice"
SUPPLEMENTARY = "supplementary"
TITLES = {
    "td": "Технический директор",
    "od": "Операционный директор",
    "gd": "Генеральный директор",
    "fd": "Финансовый директор",
}
COMMENT_MIN = 10


def _stage(order: int, key: str, positions: dict, **extra) -> dict:
    return {"order": order, "name": TITLES[key], "quorum": "any",
            "position_ids": [positions[key]], **extra}


class Command(BaseCommand):
    help = ("Завести маршруты согласования модуля БЗО (заявка: ТД → ОД; договор: "
            "ФД → ТД → ОД → ГД; допсоглашение: ФД при росте суммы; счёт: ФД) с флагами БЗО.")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        for key, title in TITLES.items():
            parser.add_argument(f"--{key}", type=int, default=None,
                                help=f"id должности «{title}» (по умолчанию — по названию)")
        parser.add_argument("--dry-run", action="store_true")

    def _positions(self, options) -> dict[str, int | None]:
        found = hr.positions_by_title(list(TITLES.values()))
        return {key: options.get(key) or found.get(title) for key, title in TITLES.items()}

    def _routes(self, positions: dict) -> list[dict]:
        """Маршруты, которые можно завести с этими должностями."""
        routes = [{
            "subject_type": REQUEST, "scope": "", "what": "заявки на закупку",
            "name": "Заявка на закупку: ТД → ОД",
            "stages": [_stage(1, "td", positions), _stage(2, "od", positions)],
            "flags": {},
        }]
        if positions["fd"] and positions["gd"]:
            routes.append({
                "subject_type": AGREEMENT, "scope": "", "what": "договора",
                "name": "Договор: ФД → ТД → ОД → ГД",
                "stages": [_stage(1, "fd", positions), _stage(2, "td", positions),
                           _stage(3, "od", positions), _stage(4, "gd", positions)],
                "flags": {},
            })
            routes.append({
                "subject_type": AGREEMENT, "scope": SUPPLEMENTARY, "what": "допсоглашения",
                "name": "Допсоглашение: ФД при росте суммы",
                "stages": [_stage(1, "fd", positions, condition=[
                    {"field": "amount_delta", "op": "gt", "value": 0}])],
                "flags": {"skip_unmatched_groups": True},
            })
        if positions["fd"]:
            routes.append({
                "subject_type": INVOICE, "scope": "", "what": "счёта на оплату",
                "name": "Счёт на оплату: решение ФД",
                "stages": [_stage(1, "fd", positions, requirement_key="bpp:budget")],
                "flags": {},
            })
        return routes

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
                                      f"не настроено, маршруты договора не заводятся")
            base_flags = {
                "forbid_self_approval": True,
                "reject_comment_min": COMMENT_MIN,
                "lazy_resolution": True,
                "escalation_position_id": positions["gd"],
                "no_executor_notify_position_ids": [p for p in (positions["gd"],) if p],
                "self_skip_notify_position_ids": [p for p in (positions["fd"],) if p],
            }
            for route in self._routes(positions):
                self._configure(route, {**base_flags, **route["flags"]}, dry_run=dry_run)

    def _configure(self, route: dict, flags: dict, *, dry_run: bool) -> None:
        if signoff.has_active_route(route["subject_type"], route["scope"]):
            self.stdout.write(f"уже есть: активный маршрут {route['what']} — не менялся")
            return
        chain = " → ".join(f"{stage['name']} #{stage['position_ids'][0]}"
                           for stage in route["stages"])
        if dry_run:
            self.stdout.write(f"завести маршрут {route['what']}: {chain}, флаги {flags}")
            return
        try:
            route_id = signoff.configure_route(
                subject_type=route["subject_type"], name=route["name"],
                stages=route["stages"], scope=route["scope"], flags=flags)
        except signoff.RouteConflict as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"заведён маршрут {route['what']} #{route_id}")
