"""Завести маршруты согласования документов модуля БЗО (ТЗ §16.1, D-21).

По должностям управляющей компании, с флагами БЗО:

- **заявка на закупку** — «ТД → ОД»;
- **договор** — «ФД → ТД → ОД → ГД» (BR-035); у ФД и ГД признак «Выбирает
  вариант» (``votes_option``, D-25): голосуют за исходный документ или
  альтернативу, решающий голос — ГД. Пока договор не отдаёт вариантов
  (B5.1), признак ни на что не влияет. Маршрут, заведённый до признака,
  команда не меняет — галочку ставят в редакторе маршрута;
- **допсоглашение** (область ``supplementary``, D-18) — этап ФД только при
  росте суммы (``amount_delta > 0``); без изменения суммы этапов не остаётся
  и допсоглашение вступает в силу сразу (флаг ``skip_unmatched_groups``);
- **счёт на оплату** — один этап ФД (D-12) с требованием ``bpp:budget``:
  «Согласовать» из общего инбокса проходит проверку бюджета, как «Оплатить»;
- **заявка на подотчёт** и **авансовый отчёт** — один этап ФД. В ТЗ маршрута
  подотчёта нет (подотчёт пришёл из ``contracts``), это умолчание: без
  маршрута заявку на подотчёт не отправить вовсе.

Флаги у всех маршрутов:

- запрет самосогласования, эскалация на ГД, уведомление ФД, если автор —
  сам ГД (BR-061, D-22);
- комментарий к отказу и возврату — не короче 10 символов (BR-060);
- ленивое разрешение исполнителей и «Нет исполнителя» с уведомлением ГД
  (ТЗ §16.1 п.2, п.5).

Должности ищутся по названию (``hr.positions_by_title``) — сначала в штате
самой компании, затем выше по дереву владения (B8.1: директора — в штате
холдинга, у дочерних их нет); вывод называет компанию каждой найденной
должности. Явные ``--td``/``--od``/``--gd``/``--fd`` их перебивают: ``12`` —
должность своей компании, ``hi-tech-group:12`` — вышестоящей. Идемпотентна:
активный маршрут типа и области не трогает — чтобы заменить его,
деактивируйте старый на странице маршрута. Маршруты договора требуют всех
четырёх должностей; без ФД или ГД заводится только маршрут заявки.

Предупреждает, но не останавливается: держатели должностей холдинга без
членства в компании не смогут перейти к её документам (членство и права —
A8.1, команда ``bpp_group_directors``), а выключенный у компании модуль ``bpp`` маршрутами не пользуется.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies import interface as companies
from apps.hr import interface as hr
from apps.signoff import interface as signoff
from htqweb.tenancy.db import use_company

REQUEST = "bpp.purchase_request"
AGREEMENT = "bpp.agreement"
INVOICE = "bpp.invoice"
ACCOUNTABLE = "bpp.accountable_funds_request"
ADVANCE_REPORT = "bpp.advance_report"
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
            "positions": [positions[key]], **extra}


def _ref(company: str, position_id: int) -> dict:
    """Должность парой, как её принимает signoff (B8.1): ``company`` пуст у
    своей компании."""
    return {"company": company, "position_id": int(position_id)}


def _parse_override(value: str | None, *, own: str) -> dict | None:
    """``12`` — должность своей компании, ``hi-tech-group:12`` — вышестоящей."""
    if not value:
        return None
    company, _, position_id = value.rpartition(":")
    try:
        return _ref("" if company in ("", own) else company, int(position_id))
    except ValueError as exc:
        raise CommandError(f"Должность «{value}»: ожидается id или <компания>:<id>") from exc


class Command(BaseCommand):
    help = ("Завести маршруты согласования модуля БЗО (заявка: ТД → ОД; договор: "
            "ФД → ТД → ОД → ГД; допсоглашение: ФД при росте суммы; счёт, подотчёт и "
            "авансовый отчёт: ФД) с флагами БЗО. Должности директоров берутся из "
            "своей компании, а если их там нет — из вышестоящей (холдинга).")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        for key, title in TITLES.items():
            parser.add_argument(f"--{key}", default=None,
                                help=f"должность «{title}»: id своей компании или "
                                     f"<компания>:<id> вышестоящей (по умолчанию — по "
                                     f"названию, сначала в своей компании, затем выше)")
        parser.add_argument("--dry-run", action="store_true")

    def _positions(self, company: str, options) -> dict[str, dict | None]:
        """Должности по названию — в своей компании, затем выше по дереву,
        ближайшая первой; явный аргумент перебивает поиск."""
        found: dict[str, dict] = {}
        for title, position_id in hr.positions_by_title(list(TITLES.values())).items():
            found[title] = _ref("", position_id)
        for upper in companies.ancestor_slugs(company):
            missing = [title for title in TITLES.values() if title not in found]
            if not missing:
                break
            with use_company(upper):
                for title, position_id in hr.positions_by_title(missing).items():
                    found[title] = _ref(upper, position_id)
        return {key: _parse_override(options.get(key), own=company) or found.get(title)
                for key, title in TITLES.items()}

    def _describe_positions(self, positions: dict) -> None:
        for key, ref in positions.items():
            if ref is None:
                continue
            where = f"компания {ref['company']}" if ref["company"] else "своя компания"
            self.stdout.write(f"{TITLES[key]}: должность #{ref['position_id']} ({where})")

    def _warn(self, company: str, positions: dict) -> None:
        """Держатели должностей вышестоящих компаний без членства здесь не
        смогут перейти к документам этой компании — только решать из своей
        очереди, если маршрут это разрешит. Членство выдаёт ``bpp_group_directors``
        (A8.1)."""
        members = set(companies.active_member_ids(company))
        for key, ref in positions.items():
            if ref is None or not ref["company"]:
                continue
            with use_company(ref["company"]):
                holders = hr.resolve_position_users([ref["position_id"]]).get(
                    ref["position_id"], [])
            outsiders = [user_id for user_id in holders if user_id not in members]
            if outsiders:
                self.stdout.write(
                    f"внимание: у держателей должности «{TITLES[key]}» компании "
                    f"{ref['company']} нет членства в {company} (учётки "
                    f"{', '.join(map(str, outsiders))}) — перейти к документам компании они "
                    f"не смогут; выдайте его: manage.py bpp_group_directors --holding <холдинг>")
        enabled, _ = companies.module_enabled(company, "bpp")
        if not enabled:
            self.stdout.write(f"внимание: модуль bpp у компании {company} выключен — "
                              f"маршруты заведены, но документов модуля не будет")

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
                # Альтернативу выбирают ФД и ГД, решает ГД (D-25, B5.1).
                "stages": [_stage(1, "fd", positions, votes_option=True),
                           _stage(2, "td", positions), _stage(3, "od", positions),
                           _stage(4, "gd", positions, votes_option=True)],
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
            routes.append({
                "subject_type": ACCOUNTABLE, "scope": "", "what": "заявки на подотчёт",
                "name": "Заявка на подотчёт: ФД",
                "stages": [_stage(1, "fd", positions)],
                "flags": {},
            })
            routes.append({
                "subject_type": ADVANCE_REPORT, "scope": "", "what": "авансового отчёта",
                "name": "Авансовый отчёт: ФД",
                "stages": [_stage(1, "fd", positions)],
                "flags": {},
            })
        return routes

    def handle(self, *args, company, dry_run, **options):
        # SET search_path молча принимает несуществующую схему и уводит запросы
        # в public — маршруты завелись бы не той компании.
        if companies.get_company(company) is None or not companies.schema_exists(company):
            raise CommandError(f"Компании «{company}» нет или у неё нет схемы — сначала "
                               f"company_create / migrate_companies.")
        with use_company(company):
            positions = self._positions(company, options)
            missing = [TITLES[key] for key in ("td", "od") if not positions[key]]
            if missing:
                raise CommandError(
                    f"Нет должностей: {', '.join(missing)} — ни в компании, ни выше по "
                    f"дереву; заведите их в структуре или передайте --td/--od.")
            self._describe_positions(positions)
            for key in ("gd", "fd"):
                if not positions[key]:
                    self.stdout.write(f"нет должности «{TITLES[key]}» — "
                                      f"{'эскалация' if key == 'gd' else 'уведомление'} "
                                      f"не настроено, маршруты договора не заводятся")
            self._warn(company, positions)
            for route in self._routes(positions):
                self._configure(route, {**self._base_flags(positions), **route["flags"]},
                                dry_run=dry_run)

    @staticmethod
    def _base_flags(positions: dict) -> dict:
        """Флаги БЗО; ГД и ФД — своей компании или вышестоящей (B8.1)."""
        gd, fd = positions["gd"], positions["fd"]

        def own(ref):
            return [ref["position_id"]] if ref and not ref["company"] else []

        def foreign(ref):
            return [ref] if ref and ref["company"] else []

        return {
            "forbid_self_approval": True,
            "reject_comment_min": COMMENT_MIN,
            "lazy_resolution": True,
            "escalation_position_id": gd["position_id"] if gd else None,
            "escalation_position_company": gd["company"] if gd else "",
            "no_executor_notify_position_ids": own(gd),
            "no_executor_notify_foreign": foreign(gd),
            "self_skip_notify_position_ids": own(fd),
            "self_skip_notify_foreign": foreign(fd),
        }

    def _configure(self, route: dict, flags: dict, *, dry_run: bool) -> None:
        if signoff.has_active_route(route["subject_type"], route["scope"]):
            self.stdout.write(f"уже есть: активный маршрут {route['what']} — не менялся")
            return

        def where(ref: dict) -> str:
            return (f"#{ref['position_id']}" if not ref["company"]
                    else f"{ref['company']}:#{ref['position_id']}")

        chain = " → ".join(f"{stage['name']} {where(stage['positions'][0])}"
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
