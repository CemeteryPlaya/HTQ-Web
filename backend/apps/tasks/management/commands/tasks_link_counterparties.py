"""Связать партнёров с контрагентами модуля «Закупки и оплаты» (A6.1, D-S6-2).

``manage.py tasks_link_counterparties --company <slug> [--dry-run]``

Партнёр (``tasks.Contractor``) ссылался на контрагента «Договоров»
(``counterparty_id``). Перенос B6.1 (``bpp_migrate_contracts``) завёл по
каждому контрагенту «Договоров» контрагента модуля и запомнил связь
переноса. Команда ставит партнёру ТОГО ЖЕ контрагента модуля
(``bpp_counterparty_id``) — по связи, через ``bpp.interface.migrated_targets``.
Запускается в ранбуке выкатки после ``bpp_migrate_contracts``.

**Единственное место в ``apps.tasks``, где читается старое
``Contractor.counterparty_id``** (сторож — ``tests/
test_contractor_counterparty.py::test_old_field_is_not_read``): сервисы,
ручки и интерфейс работают только с новым полем.

Отчёт — по партнёру, пять исходов:

* **связан** — поставлен контрагент модуля;
* **уже связан** — у партнёра уже этот контрагент (повторный прогон);
* **оставлен** — у партнёра уже другой контрагент модуля: его поставили
  руками на экране партнёра, и команда ручную связь не затирает;
* **без пары** — у партнёра не было контрагента «Договоров» или тот не
  перенесён: связать руками на экране партнёра;
* **конфликт** — два партнёра указывают на одного контрагента модуля (два
  контрагента «Договоров» перенеслись в одного, по одному БИН), контрагент
  уже занят другим партнёром или БИН/ИИН партнёра с ним расходится. Ни один
  из спорных не связывается — решает человек на экране партнёра. В отчёт, а
  не ``IntegrityError``: уникальность среди непустых держит и БД, но падение
  посреди прогона ничего бы не объяснило.

Статус целевого контрагента не проверяется (заблокированный тоже свяжется, как
уже стоящая связь); статус проверяет только ручная смена связи на экране.

Идемпотентна: повтор после успешного прогона — одни «уже связан». Всё в
одной транзакции; ``--dry-run`` печатает тот же отчёт и ничего не пишет.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bpp import interface as bpp
from apps.core.services import ServiceDisabled
from apps.tasks.models import Contractor
from apps.tasks.services.contractor_service import MIGRATED_COUNTERPARTY
from htqweb.tenancy.db import use_company

_KZ_BIN = re.compile(r"\d{12}")

LINKED = "связан"
ALREADY = "уже связан"
KEPT = "оставлен"
UNPAIRED = "без пары"
CONFLICT = "конфликт"
OUTCOMES = (LINKED, ALREADY, KEPT, UNPAIRED, CONFLICT)


@dataclass
class LinkReport:
    rows: list[dict] = field(default_factory=list)

    def add(self, outcome: str, partner: Contractor, detail: str, target: str = "") -> None:
        self.rows.append({"outcome": outcome, "partner_id": partner.pk,
                          "partner": partner.name, "target": target, "detail": detail})

    def count(self, outcome: str) -> int:
        return sum(1 for row in self.rows if row["outcome"] == outcome)

    def of(self, outcome: str) -> list[dict]:
        return [row for row in self.rows if row["outcome"] == outcome]


def _targets(source_ids: list[int]) -> dict[int, str]:
    source_type, target_type = MIGRATED_COUNTERPARTY
    out = {}
    for source, targets in bpp.migrated_targets(source_type, source_ids).items():
        for target in targets:
            if target["target_type"] == target_type:
                out[int(source)] = target["target_id"]
    return out


def link_counterparties(*, dry_run: bool) -> LinkReport:
    """Связать партнёров текущей компании; зовётся в контексте компании."""
    report = LinkReport()
    partners = list(Contractor.objects.order_by("name", "pk"))
    targets = _targets([p.counterparty_id for p in partners if p.counterparty_id is not None])
    cards = bpp.counterparty_brief(set(targets.values()))
    # Кто уже держит контрагента модуля — ручные связи и прошлые прогоны.
    holders = {p.bpp_counterparty_id: p for p in partners if p.bpp_counterparty_id}
    # Кто его хочет в этом прогоне — чтобы два партнёра не поделили одного.
    wanted: dict[str, list[Contractor]] = defaultdict(list)

    for partner in partners:
        old = partner.counterparty_id
        target = targets.get(old) if old is not None else None
        if partner.bpp_counterparty_id:
            if target is None or partner.bpp_counterparty_id == target:
                report.add(ALREADY, partner, "контрагент модуля уже указан",
                           partner.bpp_counterparty_id)
            else:
                report.add(KEPT, partner, "связь поставлена вручную — не затирается; по "
                           f"переносу был бы {target}", partner.bpp_counterparty_id)
            continue
        if old is None:
            report.add(UNPAIRED, partner, "нет контрагента в «Договорах» — связать вручную")
            continue
        if target is None:
            report.add(UNPAIRED, partner, f"контрагент «Договоров» #{old} не перенесён — "
                       "связать вручную")
            continue
        card = cards.get(target)
        if card is None:
            report.add(UNPAIRED, partner, f"контрагент модуля {target} по связи переноса "
                       "не найден — связать вручную", target)
            continue
        holder = holders.get(target)
        if holder is not None:
            report.add(CONFLICT, partner, f"контрагент «{card['name']}» уже связан с "
                       f"партнёром «{holder.name}»", target)
            continue
        reg_number = (card["reg_number"] or "").strip()
        if partner.bin_iin and partner.bin_iin != reg_number:
            report.add(CONFLICT, partner, f"БИН/ИИН партнёра ({partner.bin_iin}) не совпадает "
                       f"с БИН/ИИН контрагента «{card['name']}» ({reg_number})", target)
            continue
        wanted[target].append(partner)

    taken_bins = {p.bin_iin for p in partners if p.bin_iin}
    for target, claimants in wanted.items():
        card = cards[target]
        if len(claimants) > 1:
            names = ", ".join(f"«{p.name}»" for p in claimants)
            for partner in claimants:
                report.add(CONFLICT, partner, f"на контрагента «{card['name']}» указывают "
                           f"несколько партнёров: {names}", target)
            continue
        [partner] = claimants
        updates = {"bpp_counterparty_id": target}
        reg_number = (card["reg_number"] or "").strip()
        if not partner.bin_iin and _KZ_BIN.fullmatch(reg_number) \
                and reg_number not in taken_bins:
            # Как при связывании на экране: пустой БИН — «не вписали».
            updates["bin_iin"] = reg_number
            taken_bins.add(reg_number)
        if not dry_run:
            Contractor.objects.filter(pk=partner.pk).update(**updates)
        report.add(LINKED, partner, f"контрагент «{card['name']}» ({reg_number})", target)
    return report


class Command(BaseCommand):
    help = ("Связать партнёров задач с контрагентами модуля «Закупки и оплаты» по связям "
            "переноса из «Договоров» (после bpp_migrate_contracts).")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, dry_run, **options):
        try:
            with use_company(company), transaction.atomic():
                report = link_counterparties(dry_run=dry_run)
        except ServiceDisabled as exc:
            raise CommandError(
                "Модуль «Бюджет, закупки и оплаты» выключен у платформы или "
                f"компании «{company}» — включите его и повторите: {exc}") from exc
        head = "ПРОБНЫЙ ПРОГОН — ничего не записано. " if dry_run else ""
        self.stdout.write(head + "Итого: " + ", ".join(
            f"{outcome} — {report.count(outcome)}" for outcome in OUTCOMES))
        for outcome in (CONFLICT, UNPAIRED, KEPT, LINKED):
            rows = report.of(outcome)
            if not rows:
                continue
            self.stdout.write(f"\n{outcome.capitalize()} ({len(rows)}):")
            for row in rows:
                self.stdout.write(f"  #{row['partner_id']} «{row['partner']}»: {row['detail']}")
