"""Документы переноса (B6.1, задача 5).

Переносятся ОТКРЫТЫЕ документы (Q-B36); закрытые остаются в ``contracts``, а
их вклад в «занято» уходит в сальдо статьи (задача 6, D-B61-1).

Документы и технические заявки пишутся моделями напрямую, а не сервисами
черновиков: сервисы проверяют бюджет, пересчитывают сумму позиции из цены и
количества и шлют документ по маршруту — перенос же обязан повторить старые
суммы до копейки и поставить документ сразу в его статус. Номера, НДС и
журнал — из модуля (``next_number``, ``calc.vat_amount``, ``audit``), так что
перенесённый документ неотличим от заведённого руками, кроме признака
``is_migrated`` и записи журнала «migrated» с источником.

Техническая заявка переноса (Q-D06) — утверждённая, скрытая (``is_migrated``),
по одной позиции на позицию документа: без неё договор и счёт не имеют
обязательных позиций, а CALC-002 не держит их резерв.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.bpp.models import (
    AccountableFundsRequest,
    AccountableStatus,
    AdvanceReport,
    Agreement,
    AgreementItem,
    AgreementStatus,
    AgreementType,
    Invoice,
    InvoiceBasis,
    InvoiceLine,
    InvoiceStatus,
    ItemStatus,
    PaymentMark,
    PurchaseRequest,
    PurchaseRequestItem,
    RateSource,
    RequestStatus,
    VatSource,
)
from apps.bpp.services import calc
from apps.bpp.services.actor import ROLE_GROUP
from apps.bpp.services.core import audit
from apps.bpp.services.core.numbering import next_number
from apps.contracts import interface as contracts
from apps.files import interface as files
from apps.refdata import interface as refdata

from . import links

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

AGREEMENT_STATUS = {"draft": AgreementStatus.DRAFT, "on_review": AgreementStatus.DRAFT,
                    "approved": AgreementStatus.ACTIVE, "signed": AgreementStatus.ACTIVE}
INVOICE_STATUS = {"draft": InvoiceStatus.DRAFT, "on_review": InvoiceStatus.DRAFT,
                  "approved": InvoiceStatus.TO_PAY}
PAYMENT_STATUS = {"draft": InvoiceStatus.DRAFT, "on_review": InvoiceStatus.DRAFT,
                  "awaiting_accounting": InvoiceStatus.TO_PAY, "closed": InvoiceStatus.PAID}
ACCOUNTABLE_STATUS = {"draft": AccountableStatus.DRAFT, "on_review": AccountableStatus.DRAFT,
                      "awaiting_accounting": AccountableStatus.AWAITING_ACCOUNTING,
                      "awaiting_advance_report": AccountableStatus.AWAITING_REPORT}
#: Тип файла закрывающего документа по виду платёжного документа.
PAYMENT_FILE_TYPE = {"contract_payment": "invoice", "completion_act": "act",
                     "goods_invoice": "waybill"}
PAYMENT_LABEL = {"contract_payment": "оплата по договору", "advance_payment": "предоплата",
                 "completion_act": "АВР", "goods_invoice": "накладная"}
#: Единицы старых позиций (свободный текст) → код справочника. Нет в таблице
#: и нет единицы с таким кодом — «шт.», и позиция попадает в отчёт.
UNIT_CODES = {"шт": "pcs", "шт.": "pcs", "штук": "pcs", "т": "t", "тн": "t", "тонна": "t",
              "м": "m", "м.": "m", "метр": "m", "кг": "kg", "м2": "m2", "м²": "m2",
              "м3": "m3", "м³": "m3", "л": "l", "усл": "unit", "усл.": "unit", "компл": "set",
              "компл.": "set", "комплект": "set"}


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


class Documents:
    """Перенос документов одной компании. Держит соответствия, нужные
    соседним шагам: договор → его позиции (для счетов по договору и сальдо)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.report = ctx.report
        self.actor_id = ctx.actor.user_id
        self.today = timezone.localdate()
        self.lines: dict[int, tuple[int, int, str]] = {}
        for budget in ctx.snapshot["budgets"]:
            for line in budget["lines"]:
                self.lines[line["id"]] = (budget["administrator_id"], line["program_id"],
                                          budget["currency"])
        self.agreements: dict[int, Agreement] = {}
        self.agreement_items: dict[int, list[PurchaseRequestItem]] = {}
        self.revoke: dict[str, list[int]] = {}
        self._units: dict[str, str | None] = {}

    # ── общее ──────────────────────────────────────────────────────────

    def target(self, line_id: int | None, *, admin_id=None, program_id=None, kind: str,
               old_id) -> tuple[str, dict] | None:
        """(ключ «Проекта», статья) строки бюджета — или ``None`` с записью
        в отчёт: строка в бюджете не в KZT, проект или программа не в карте."""
        if line_id is not None:
            admin_id, program_id, currency = self.lines[line_id]
            if currency != "KZT":
                self.report.add("Не перенесено", kind=kind, old_id=old_id,
                                reason=f"строка бюджета в {currency} — лимиты модуля в KZT")
                return None
        project_id = self.ctx.project_by_admin.get(admin_id)
        article = self.ctx.article_map.get(program_id)
        if project_id is None or article is None:
            self.report.add("Не перенесено", kind=kind, old_id=old_id,
                            reason="проект или программа не в карте переноса")
            return None
        return project_id, article

    def author(self, created_by) -> int:
        return created_by or self.actor_id

    def uom(self, text: str, *, kind: str, old_id) -> str:
        key = (text or "").strip().lower()
        if key not in self._units:
            self._units[key] = refdata.uom_id(UNIT_CODES.get(key, key)) if key else None
        found = self._units[key]
        if found:
            return found
        if key:
            self.report.add("Не перенесено", kind=kind, old_id=old_id,
                            reason=f"единица «{text}» не найдена — позиция в «шт.»")
        return refdata.uom_id("pcs")

    def adopt(self, owner_type: str, owner, file_type: str, media_file_id, *, kind: str,
              old_id, uploaded_by: int) -> None:
        if not media_file_id:
            return
        try:
            files.adopt_media_file(owner_type, owner.pk, file_type=file_type,
                                   media_file_id=str(media_file_id), uploaded_by_id=uploaded_by)
        except Exception as exc:  # noqa: BLE001 — файл не должен ронять перенос документа
            self.report.add("Не перенесено", kind=f"файл: {kind}", old_id=old_id,
                            reason=f"файл {media_file_id} не перенесён: {exc}")

    def pending_revoke(self, subject_type: str, row: dict) -> None:
        if row.get("approval_state") == "pending":
            self.revoke.setdefault(subject_type, []).append(row["id"])

    def done(self, kind: str, row: dict, new_number: str, status: str, *, old_number="") -> None:
        self.report.add("Документы", kind=kind, old_id=row["id"], old_number=old_number,
                        new_number=new_number, status=status)
        if row.get("status") == "on_review":
            self.report.add("Переотправить", kind=kind, new_number=new_number,
                            author_id=self.author(row.get("created_by")))

    # ── техническая заявка переноса ───────────────────────────────────

    def tech_request(self, *, project_id: str, article: dict, author_id: int, purpose: str,
                     purchase_type: str, items: list[tuple[str, str, Decimal, Decimal]],
                     source: tuple[str, object]) -> list[PurchaseRequestItem]:
        """Утверждённая скрытая заявка (Q-D06); позиции — ``(наименование,
        единица, количество, сумма)``. Сумма позиции задана, а не выведена из
        цены: округление цены не должно сдвинуть резерв на копейки."""
        role = next((role for role, group in ROLE_GROUP.items() if group == article["group"]),
                    "sn")
        req = PurchaseRequest.objects.create(
            number=next_number("ЗЗ"), author_id=author_id, initiator_role=role,
            project_id=project_id, article_id=article["id"], purchase_type=purchase_type,
            need_date=self.today, justification=purpose[:2000], currency_code="KZT",
            total_amount=sum((amount for *_, amount in items), ZERO),
            status=RequestStatus.APPROVED, approval_state="approved", is_migrated=True,
            created_by=self.actor_id, updated_by=self.actor_id)
        rows = []
        for index, (name, uom_id, qty, amount) in enumerate(items, start=1):
            price = max((amount / qty).quantize(CENT, rounding=ROUND_HALF_UP), CENT)
            rows.append(PurchaseRequestItem.objects.create(
                request=req, line_no=index, sys_number=f"{req.number}-{index:02d}",
                name=name[:500], uom_id=uom_id, qty=qty, price=price, amount=amount,
                need_date=self.today, status=ItemStatus.OPEN, executor_id=author_id,
                created_by=self.actor_id, updated_by=self.actor_id))
        audit.record(req, "migrated", actor_id=self.actor_id,
                     changes={"source": f"{source[0]}:{source[1]}"})
        links.link(source[0], source[1], "bpp.purchase_request", req.pk)
        return rows

    # ── договоры ──────────────────────────────────────────────────────

    def request_items_for(self, row: dict, author_id: int, is_open: bool) -> list[tuple]:
        """Позиции технической заявки договора. Позиции старого договора —
        если у каждой есть сумма и вместе они дают сумму договора; иначе одна
        позиция «Предмет договора» (Q-D06). Открытый договор резервирует
        только свои платежи (D-09): позиция на сумму его учтённых оплат, не
        меньше копейки (сумма позиции заявки > 0)."""
        kind = "договор"
        if is_open:
            spent = sum((p["committed"] for p in self.ctx.snapshot["payments"]
                         if p["agreement_id"] == row["id"]), ZERO)
            if spent == 0:
                self.report.add("Не перенесено", kind=kind, old_id=row["id"],
                                reason="открытый договор без учтённых оплат — резерв "
                                       "технической позиции 0,01 (ожидаемое расхождение)")
            name = row["subject"] or row["name"] or "Предмет договора"
            return [(name, self.uom("", kind=kind, old_id=row["id"]), Decimal("1"),
                     max(_money(spent), CENT))]
        old = row["items"]
        if old and all(item["amount"] for item in old) \
                and sum(_money(item["amount"]) for item in old) == _money(row["amount"]):
            return [(item["name"], self.uom(item["unit"], kind=kind, old_id=row["id"]),
                     Decimal(item["quantity"]), _money(item["amount"])) for item in old]
        if old:
            self.report.add("Не перенесено", kind=kind, old_id=row["id"],
                            reason="позиции без сумм или не дают сумму договора — сведены "
                                   "в одну «Предмет договора»")
        return [(row["subject"] or row["name"] or "Предмет договора",
                 self.uom("", kind=kind, old_id=row["id"]), Decimal("1"), _money(row["amount"]))]

    def migrate_agreements(self) -> None:
        for row in self.ctx.snapshot["agreements"]:
            if row["status"] not in AGREEMENT_STATUS:
                continue                                         # закрытый — сальдо
            if row["direction"] == "income":
                self.report.add("Не перенесено", kind="договор", old_id=row["id"],
                                reason="договор-поступление — в модуле только расход")
                continue
            linked = links.target_of("contracts.agreement", row["id"], "bpp.agreement")
            if linked:
                agr = Agreement.objects.get(pk=linked)
                self.agreements[row["id"]] = agr
                self.agreement_items[row["id"]] = [
                    item.request_item for item in agr.items.select_related("request_item")
                    .order_by("request_item__line_no")]
                continue
            target = self.target(row["budget_line_id"], kind="договор", old_id=row["id"])
            if target is None:
                continue
            project_id, article = target
            author_id = self.author(row["created_by"])
            is_open = row["contract_type"] == "framework"
            agreement_type = (AgreementType.GOODS if row["kind"] == "goods"
                              else AgreementType.WORKS)
            items = self.tech_request(
                project_id=project_id, article=article, author_id=author_id,
                purpose=f"Перенос договора {row['number']} из «Договоров»",
                purchase_type=agreement_type,
                items=self.request_items_for(row, author_id, is_open),
                source=("contracts.agreement", row["id"]))
            status = AGREEMENT_STATUS[row["status"]]
            amount = None if is_open else _money(row["amount"])
            vat_amount = None
            if row["has_vat"] and amount is not None:
                vat_amount = (_money(row["vat_amount"]) if row["vat_amount"] is not None
                              else calc.vat_amount(amount, row["vat_rate"]))
            if len(row["number"]) > 50:
                self.report.add("Не перенесено", kind="договор", old_id=row["id"],
                                reason=f"номер «{row['number']}» длиннее 50 символов — обрезан")
            agr = Agreement.objects.create(
                number=next_number("ДГ"), ext_number=row["number"][:50],
                ext_date=row["signed_date"], name=row["name"][:500], project_id=project_id,
                article_id=article["id"], counterparty=self.ctx.counterparties[
                    row["counterparty_id"]],
                agreement_type=agreement_type, is_open=is_open, amount=amount,
                currency_code="KZT", with_vat=row["has_vat"],
                vat_rate=row["vat_rate"] if row["has_vat"] else None,
                vat_source=VatSource.MANUAL if row["has_vat"] else "", vat_amount=vat_amount,
                valid_to=row["end_date"], status=status,
                approval_state="approved" if status == AgreementStatus.ACTIVE else "draft",
                author_id=author_id, initiator_role=items[0].request.initiator_role,
                counterparty_confirmed=True, is_migrated=True,
                created_by=self.actor_id, updated_by=self.actor_id)
            for item in items:
                AgreementItem.objects.create(agreement=agr, request_item=item, qty=item.qty,
                                             amount=None if is_open else item.amount,
                                             created_by=self.actor_id, updated_by=self.actor_id)
            self.adopt("bpp.agreement", agr, "agreement", row["file_id"], kind="договор",
                       old_id=row["id"], uploaded_by=author_id)
            audit.record(agr, "migrated", actor_id=self.actor_id,
                         changes={"source": f"contracts.agreement:{row['id']}",
                                  "old_number": row["number"], "old_status": row["status"]})
            links.link("contracts.agreement", row["id"], "bpp.agreement", agr.pk)
            self.pending_revoke("contracts.agreement", row)
            self.agreements[row["id"]] = agr
            self.agreement_items[row["id"]] = items
            self.done("договор", row, agr.number, agr.get_status_display(),
                      old_number=row["number"])

    # ── счета ─────────────────────────────────────────────────────────

    def _invoice(self, *, basis: str, agreement: Agreement | None, project_id: str,
                 article_id: str, counterparty, amount: Decimal, status: str, author_id: int,
                 role: str, purchase_type: str, is_advance: bool, ext_date: date | None,
                 comment: str, lines: list[tuple[PurchaseRequestItem, Decimal, Decimal]],
                 source: tuple[str, object]) -> Invoice:
        inv = Invoice.objects.create(
            number=next_number("СЧ"), basis=basis, agreement=agreement, project_id=project_id,
            article_id=article_id, counterparty=counterparty, ext_date=ext_date,
            amount=amount, currency_code="KZT", rate=Decimal("1"), rate_source=RateSource.KZT,
            amount_kzt=amount, with_vat=agreement.with_vat if agreement else True,
            vat_rate=agreement.vat_rate if agreement else None,
            vat_source=agreement.vat_source if agreement else "",
            purchase_type=purchase_type, is_advance=is_advance, status=status,
            approval_state="approved" if status != InvoiceStatus.DRAFT else "draft",
            fd_decided_at=timezone.now() if status != InvoiceStatus.DRAFT else None,
            author_comment=comment[:2000], author_id=author_id, initiator_role=role,
            counterparty_confirmed=True, is_migrated=True,
            created_by=self.actor_id, updated_by=self.actor_id)
        for item, qty, line_amount in lines:
            InvoiceLine.objects.create(invoice=inv, request_item=item, qty=qty,
                                       amount=line_amount, created_by=self.actor_id,
                                       updated_by=self.actor_id)
        audit.record(inv, "migrated", actor_id=self.actor_id,
                     changes={"source": f"{source[0]}:{source[1]}"})
        links.link(source[0], source[1], "bpp.invoice", inv.pk)
        return inv

    @staticmethod
    def split(amount: Decimal, items: list[PurchaseRequestItem]) -> list[tuple]:
        """Сумма платежа по позициям договора пропорционально их суммам;
        остаток округления — последней позиции. Количество — та же доля."""
        total = sum((item.amount for item in items), ZERO)
        out, left = [], amount
        for index, item in enumerate(items):
            share = left if index == len(items) - 1 else \
                (amount * item.amount / total).quantize(CENT, rounding=ROUND_HALF_UP)
            left -= share
            if share <= 0:
                continue
            qty = max((item.qty * share / item.amount).quantize(Decimal("0.001")),
                      Decimal("0.001"))
            out.append((item, qty, share))
        return out

    def migrate_invoices(self) -> None:
        """Счета без договора: открытые — «Черновик» или «К оплате»."""
        for row in self.ctx.snapshot["invoices"]:
            if row["status"] not in INVOICE_STATUS:
                continue
            if links.target_of("contracts.invoice", row["id"], "bpp.invoice"):
                continue
            target = self.target(row["budget_line_id"], kind="счёт", old_id=row["id"])
            if target is None:
                continue
            project_id, article = target
            author_id = self.author(row["created_by"])
            amount = _money(row["amount"])
            items = self.tech_request(
                project_id=project_id, article=article, author_id=author_id,
                purpose=f"Перенос счёта «{row['name']}» из «Договоров»", purchase_type="",
                items=[(row["name"], self.uom("", kind="счёт", old_id=row["id"]),
                        Decimal("1"), amount)],
                source=("contracts.invoice", row["id"]))
            inv = self._invoice(
                basis=InvoiceBasis.NO_CONTRACT, agreement=None, project_id=project_id,
                article_id=article["id"], counterparty=self.ctx.counterparties[
                    row["counterparty_id"]], amount=amount,
                status=INVOICE_STATUS[row["status"]], author_id=author_id,
                role=items[0].request.initiator_role, purchase_type="", is_advance=False,
                ext_date=row["document_date"],
                comment="\n".join(part for part in (row["name"], row["note"]) if part),
                lines=[(items[0], Decimal("1"), amount)],
                source=("contracts.invoice", row["id"]))
            self.adopt("bpp.invoice", inv, "invoice", row["file_id"], kind="счёт",
                       old_id=row["id"], uploaded_by=author_id)
            self.pending_revoke("contracts.invoice", row)
            self.done("счёт", row, inv.number, inv.get_status_display())

    def migrate_payments(self) -> None:
        """Платёжные документы перенесённого договора — счета по договору
        (D-B61-6); проведённые — «Оплачено» с отметкой оплаты."""
        for row in self.ctx.snapshot["payments"]:
            agr = self.agreements.get(row["agreement_id"])
            label = PAYMENT_LABEL[row["kind"]]
            if agr is None:
                continue                         # договор закрыт или не перенесён — сальдо
            if links.target_of(f"contracts.{row['kind']}", row["id"], "bpp.invoice"):
                continue
            status = PAYMENT_STATUS.get(row["status"])
            if status is None:
                self.report.add("Не перенесено", kind=label, old_id=row["id"],
                                reason=f"статус «{row['status']}»")
                continue
            author_id = self.author(row["created_by"])
            amount = _money(row["amount"])
            inv = self._invoice(
                basis=InvoiceBasis.CONTRACT, agreement=agr, project_id=str(agr.project_id),
                article_id=str(agr.article_id), counterparty=agr.counterparty, amount=amount,
                status=status, author_id=author_id, role=agr.initiator_role,
                purchase_type=agr.agreement_type, is_advance=row["kind"] == "advance_payment",
                ext_date=row["document_date"], comment=f"Перенос: {label} из «Договоров»",
                lines=self.split(amount, self.agreement_items[row["agreement_id"]]),
                source=(f"contracts.{row['kind']}", row["id"]))
            if status == InvoiceStatus.PAID:
                paid_at = row["paid_at"]
                PaymentMark.objects.create(
                    invoice=inv, amount=amount,
                    pay_date=(timezone.localtime(paid_at).date() if paid_at
                              else row["document_date"] or self.today),
                    pp_number=(row["posting_number"] or "")[:50],
                    marked_by_id=row["paid_by"] or self.actor_id,
                    created_by=self.actor_id, updated_by=self.actor_id)
            if row["payment_order_file_id"]:
                self.report.add("Не перенесено", kind=f"файл: {label}", old_id=row["id"],
                                reason="платёжное поручение остаётся в «Договорах» (D-B61-7)")
            file_type = PAYMENT_FILE_TYPE.get(row["kind"])
            if file_type:
                self.adopt("bpp.invoice", inv, file_type, row["file_id"], kind=label,
                           old_id=row["id"], uploaded_by=author_id)
            self.pending_revoke(f"contracts.{row['kind']}", row)
            self.done(label, row, inv.number, inv.get_status_display())

    # ── подотчёт ──────────────────────────────────────────────────────

    def migrate_accountable(self) -> None:
        for row in self.ctx.snapshot["accountable"]:
            status = ACCOUNTABLE_STATUS.get(row["status"])
            if status is None:
                continue                                         # закрыта — сальдо
            if links.target_of("contracts.accountable_funds_request", row["id"],
                               "bpp.accountable_funds_request"):
                continue
            target = self.target(row["budget_line_id"], admin_id=row["administrator_id"],
                                 program_id=row["program_id"], kind="подотчёт",
                                 old_id=row["id"])
            if target is None:
                continue
            project_id, article = target
            req = AccountableFundsRequest.objects.create(
                number=next_number("ПО"), project_id=project_id, article_id=article["id"],
                amount=_money(row["amount"]), goal=row["goal"], status=status,
                approval_state="approved" if status != AccountableStatus.DRAFT else "draft",
                accountable_user_id=row["accountable_user_id"],
                paid_at=row["accounting_paid_at"] if row["accounting_paid"] else None,
                paid_by=row["accounting_paid_by"] if row["accounting_paid"] else None,
                is_migrated=True, created_by=self.actor_id, updated_by=self.actor_id)
            for report in row["reports"]:
                approved = report["approval_state"] == "approved"
                item = AdvanceReport.objects.create(
                    request=req, expense_name=report["expense_name"][:500],
                    amount=_money(report["amount"]),
                    approval_state="approved" if approved else "draft",
                    created_by=report["created_by"] or self.actor_id,
                    updated_by=self.actor_id)
                self.adopt("bpp.advance_report", item, "advance_report", report["file_id"],
                           kind="авансовый отчёт", old_id=report["id"],
                           uploaded_by=report["created_by"] or row["accountable_user_id"])
                links.link("contracts.advance_report", report["id"], "bpp.advance_report",
                           item.pk)
                self.pending_revoke("contracts.advance_report", report)
            audit.record(req, "migrated", actor_id=self.actor_id,
                         changes={"source": f"contracts.accountable_funds_request:{row['id']}"})
            links.link("contracts.accountable_funds_request", row["id"],
                       "bpp.accountable_funds_request", req.pk)
            self.pending_revoke("contracts.accountable_funds_request", row)
            self.done("подотчёт", row, req.number, req.get_status_display())

    # ── отзыв старых согласований ─────────────────────────────────────

    def revoke_old(self) -> None:
        """D-B61-2: старые процессы «На согласовании» отзываются — документ
        переехал черновиком, согласовывать старый экземпляр больше некому."""
        for subject_type, ids in self.revoke.items():
            contracts.revoke_for_migration(subject_type, ids)

    def run(self) -> "Documents":
        self.migrate_agreements()
        self.migrate_invoices()
        self.migrate_payments()
        self.migrate_accountable()
        self.revoke_old()
        return self
