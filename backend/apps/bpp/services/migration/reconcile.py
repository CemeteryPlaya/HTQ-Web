"""Сальдо закрытых документов и сверка остатков переноса (B6.1, задача 6).

**Сальдо (D-B61-1).** Закрытые документы остаются в ``contracts``, но их
вклад в «занято» обязан остаться и в модуле, иначе остаток статьи вырос бы
на всё уже потраченное. По каждой паре «проект × статья»: сальдо = «занято»
старых строк бюджета (``committed_by_line``) − вклад перенесённых документов
этих строк. Оно ложится одной скрытой утверждённой позицией технической
заявки «Сальдо до перехода»: CALC-002 считает её как открытую позицию с
планом = сальдо.

**Сверка.** По каждой паре: новое «Задействовано» (``committed_by_article``)
− старое «занято» = Σ ожидаемых расхождений. Ожидаемые — те, что переносом
заложены намеренно, по каждому перенесённому документу: черновик держит
резерв своей технической заявки, подотчёт «На согласовании» стал черновиком
и резерва не держит (D-B61-2), открытый договор без оплат держит 0,01 и т. п.
Всё прочее — ошибка переноса: стоп и откат всего.

Считается от текущего состояния, а не от записей первого прогона: повтор
после отзыва старых согласований меняет и «занято» строки, и вклад
отозванного документа одинаково, поэтому сверка сходится и на повторе.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from apps.bpp.models import (
    AccountableFundsRequest,
    Agreement,
    Budget,
    Invoice,
    PurchaseRequestItem,
)
from apps.bpp.services.budget import committed as calc
from apps.project import interface as projects
from apps.refdata import interface as refdata

from . import links
from .reference import MigrationStop

ZERO = Decimal("0.00")
SALDO = "contracts.saldo"


def saldo_key(project_id: str, article_id: str) -> str:
    """Ключ сальдо пары «проект × статья» в ``MigrationLink``: два UUID
    строкой длиннее поля (64), поэтому — ``uuid5`` от пары, тот же на
    каждом прогоне."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bpp-saldo:{project_id}:{article_id}"))


def _tech_items(source_type: str, source_id) -> list[PurchaseRequestItem]:
    request_id = links.target_of(source_type, source_id, "bpp.purchase_request")
    return list(PurchaseRequestItem.objects.filter(request_id=request_id)) if request_id else []


class Reconciliation:
    def __init__(self, ctx, documents):
        self.ctx = ctx
        self.docs = documents
        self.report = ctx.report
        snapshot = ctx.snapshot
        #: строка бюджета → (проект, статья) — только KZT и из карт.
        self.key_of_line: dict[int, tuple[str, str]] = {}
        for budget in snapshot["budgets"]:
            if budget["currency"] != "KZT":
                continue
            project_id = ctx.project_by_admin.get(budget["administrator_id"])
            for line in budget["lines"]:
                article = ctx.article_map.get(line["program_id"])
                if project_id and article:
                    self.key_of_line[line["id"]] = (project_id, article["id"])
        self.old: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
        for line_id, key in self.key_of_line.items():
            self.old[key] += snapshot["committed_by_line"].get(line_id, ZERO)
        self.expected: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
        self.migrated_old: dict[tuple, Decimal] = defaultdict(lambda: ZERO)

    # ── вклад перенесённых документов ─────────────────────────────────

    def _expect(self, key, delta: Decimal, kind: str, number: str, reason: str) -> None:
        if delta == 0:
            return
        self.expected[key] += delta
        codes = self._codes(key)
        self.report.add("Ожидаемые расхождения", project_code=codes[0], article_code=codes[1],
                        kind=kind, number=number, delta=delta, reason=reason)

    def _codes(self, key) -> tuple[str, str]:
        project = projects.project_brief([key[0]]).get(key[0]) or {}
        article = refdata.article_brief([key[1]]).get(key[1]) or {}
        return project.get("code", key[0]), article.get("code", key[1])

    def collect(self) -> None:
        snapshot = self.ctx.snapshot
        payments_by_agreement: dict[int, list[dict]] = defaultdict(list)
        for row in snapshot["payments"]:
            payments_by_agreement[row["agreement_id"]].append(row)

        for row in snapshot["agreements"]:
            target = links.target_of("contracts.agreement", row["id"], "bpp.agreement")
            key = self.key_of_line.get(row["budget_line_id"])
            if not target or key is None:
                continue
            old = row["committed"] + sum((p["committed"] for p in payments_by_agreement[row["id"]]),
                                         ZERO)
            new = sum((calc.committed_for_item(item)
                       for item in _tech_items("contracts.agreement", row["id"])), ZERO)
            self.migrated_old[key] += old
            number = Agreement.objects.filter(pk=target).values_list("number", flat=True).first()
            self._expect(key, new - old, "договор", number, self._agreement_reason(row, new - old))

        for row in snapshot["invoices"]:
            target = links.target_of("contracts.invoice", row["id"], "bpp.invoice")
            key = self.key_of_line.get(row["budget_line_id"])
            if not target or key is None:
                continue
            new = sum((calc.committed_for_item(item)
                       for item in _tech_items("contracts.invoice", row["id"])), ZERO)
            self.migrated_old[key] += row["committed"]
            number = Invoice.objects.filter(pk=target).values_list("number", flat=True).first()
            self._expect(key, new - row["committed"], "счёт", number,
                         "черновик и «На согласовании» держат резерв технической заявки — "
                         "в «Договорах» не держали")

        for row in snapshot["accountable"]:
            target = links.target_of("contracts.accountable_funds_request", row["id"],
                                     "bpp.accountable_funds_request")
            if not target:
                continue
            req = AccountableFundsRequest.objects.get(pk=target)
            key = (str(req.project_id), str(req.article_id))
            if row["budget_line_id"] is not None:
                self.migrated_old[self.key_of_line[row["budget_line_id"]]] += row["committed"]
            new = req.amount if req.status in calc.COMMITTING_ACCOUNTABLE_STATUSES else ZERO
            reason = ("подотчёт без строки бюджета — в «Договорах» не учитывался"
                      if row["budget_line_id"] is None else
                      "«На согласовании» перенесён черновиком — резерва не держит (D-B61-2)")
            self._expect(key, new - row["committed"], "подотчёт", req.number, reason)

    @staticmethod
    def _agreement_reason(row: dict, delta: Decimal) -> str:
        if row["contract_type"] == "framework":
            return "открытый договор без учтённых оплат — техническая позиция 0,01"
        if row["status"] == "draft" or delta == row["amount"]:
            return "черновик держит резерв технической заявки — в «Договорах» не держал"
        return "оплаты по договору больше его суммы — резерв по счетам"

    # ── сальдо ────────────────────────────────────────────────────────

    def saldo(self) -> None:
        keys = set(self.old) | set(self.migrated_old)
        for key in sorted(keys):
            amount = self.old[key] - self.migrated_old[key]
            if amount < 0:
                raise MigrationStop(f"{self._codes(key)}: вклад перенесённых документов больше "
                                    f"«занято» строк бюджета — выгрузка «Договоров» противоречива")
            source_id = saldo_key(*key)
            if amount == 0 or links.target_of(SALDO, source_id, "bpp.purchase_request"):
                continue
            article = next(a for a in self.ctx.article_map.values() if a["id"] == key[1])
            self.docs.tech_request(
                project_id=key[0], article=article, author_id=self.ctx.actor.user_id,
                purpose="Сальдо до перехода: израсходовано закрытыми документами «Договоров»",
                purchase_type="",
                items=[("Сальдо до перехода", self.docs.uom("", kind="сальдо", old_id=source_id),
                        Decimal("1"), amount)],
                source=(SALDO, source_id))

    # ── сверка ────────────────────────────────────────────────────────

    def _new_limits(self, project_id: str) -> dict[str, Decimal]:
        budget = Budget.objects.filter(project_id=project_id).first()
        if budget is None:
            return {}
        version = budget.active_version or budget.versions.order_by("version_no").first()
        return {str(line.article_id): line.limit_amount for line in version.lines.all()}

    def check(self) -> None:
        old_limits: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
        for admin_id, entry in self.ctx.limits_by_admin.items():
            project_id = self.ctx.project_by_admin.get(admin_id)
            for article_id, amount in entry["limits"].items():
                old_limits[(project_id, article_id)] += amount
        keys = sorted(set(self.old) | set(self.expected) | set(old_limits))
        wrong = []
        for key in keys:
            new_committed = calc.committed_by_article(key[0], [key[1]]).get(key[1], ZERO)
            new_limit = self._new_limits(key[0]).get(key[1], ZERO)
            diff = (new_committed - self.old[key]) - self.expected[key]
            codes = self._codes(key)
            self.report.add("Сверка", project_code=codes[0], article_code=codes[1],
                            old_limit=old_limits[key], old_committed=self.old[key],
                            old_remaining=old_limits[key] - self.old[key],
                            new_limit=new_limit, new_committed=new_committed,
                            new_remaining=new_limit - new_committed,
                            expected_diff=self.expected[key], diff=diff)
            if diff != 0:
                wrong.append(f"{codes[0]} / {codes[1]}: «Задействовано» {new_committed}, "
                             f"в «Договорах» {self.old[key]}, ожидаемое расхождение "
                             f"{self.expected[key]}, лишнее {diff}")
        if wrong:
            raise MigrationStop("остатки не сошлись:\n  " + "\n  ".join(wrong))

    # ── ключи книги CashFlow ──────────────────────────────────────────

    def cashflow_keys(self) -> None:
        """D-B62-4: документ «Договоров», загруженный когда-то из книги
        CashFlow, несёт её ключ — LARK договора или отпечаток ``ops:`` строки.
        Ключ связывается с тем, чем документ стал: перенесённым документом или
        сальдо статьи (закрытый). Импорт книги в модуль (B6.2) такие ключи
        пропускает — иначе книга, загруженная после переноса, завела бы их
        второй раз, а закрытые посчитала бы дважды: в сальдо и документом."""
        snapshot = self.ctx.snapshot
        agreement_line = {row["id"]: row["budget_line_id"] for row in snapshot["agreements"]}
        groups = (
            ("cashflow.agreement", "contracts.agreement", "bpp.agreement",
             snapshot["agreements"], lambda row: row["budget_line_id"]),
            ("cashflow.operation", "contracts.invoice", "bpp.invoice",
             snapshot["invoices"], lambda row: row["budget_line_id"]),
            ("cashflow.operation", "contracts.contract_payment", "bpp.invoice",
             [row for row in snapshot["payments"] if row["kind"] == "contract_payment"],
             lambda row: agreement_line[row["agreement_id"]]),
        )
        for key_type, source_type, target_type, rows, line_of in groups:
            for row in rows:
                external_id = (row.get("external_id") or "").strip()
                if not external_id:
                    continue
                target = links.target_of(source_type, row["id"], target_type)
                if target:
                    links.link(key_type, external_id, target_type, target)
                    continue
                key = self.key_of_line.get(line_of(row))
                if key is not None:
                    links.link(key_type, external_id, "bpp.saldo", saldo_key(*key))

    def run(self) -> None:
        self.collect()
        self.saldo()
        self.check()
        self.cashflow_keys()
