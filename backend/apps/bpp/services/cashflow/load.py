"""Загрузка книги CashFlow в модуль (B6.2, задача 4).

Только добавляет (D-B62-1): договор узнаётся по LARK, операция — по
отпечатку строки (``MigrationLink`` ``cashflow.agreement`` /
``cashflow.operation``, их же пишет перенос «Договоров», D-B62-4), и
узнанное не трогается — расхождение с книгой идёт в отчёт. Бюджет проекту
без бюджета заводится черновиком для ФД; документы проекта грузятся только
при утверждённом бюджете (D-B62-2).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from decimal import Decimal

from apps.bpp.models import (
    Agreement,
    AgreementItem,
    AgreementStatus,
    AgreementType,
    Budget,
    BudgetStatus,
    Counterparty,
    InvoiceBasis,
    InvoiceStatus,
    MigrationLink,
    PaymentMark,
)
from apps.bpp.services import calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import budgets
from apps.bpp.services.core import audit
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.migration import links
from apps.bpp.services.migration.documents import Writer
from apps.bpp.services.migration.reference import MigrationStop, _kind
from apps.bpp.services.migration.report import MigrationReport
from apps.project import interface as projects
from htqweb.errors import DomainError

from .workbook import KIND_BY_AGREEMENT, BudgetRow, OperationRow, RegistryRow

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
AGREEMENT_KEY = "cashflow.agreement"
OPERATION_KEY = "cashflow.operation"


class CashflowLoader(Writer):
    def __init__(self, *, budget: list[BudgetRow], registry: list[RegistryRow],
                 operations: list[OperationRow], project_map: dict[str, dict],
                 article_map: dict[tuple[str, str], dict], actor: Actor,
                 report: MigrationReport):
        super().__init__(report, actor.user_id)
        self.actor = actor
        self.budget, self.registry, self.operations = budget, registry, operations
        self.project_map, self.article_map = project_map, article_map
        self.project_by_admin: dict[str, str] = {}
        self.approved: set[str] = set()
        self.counterparties: dict[str, Counterparty] = {}

    # ── справочники ───────────────────────────────────────────────────

    def counterparty(self, reg_number: str, name: str) -> Counterparty:
        if reg_number not in self.counterparties:
            row = Counterparty.objects.filter(country_code="KZ", reg_number=reg_number).first()
            if row is None:
                row = Counterparty.objects.create(
                    name=name or reg_number, short_name=(name or reg_number)[:255],
                    kind=_kind("KZ", reg_number), country_code="KZ", reg_number=reg_number)
                self.report.add("Контрагенты", old_id="", reg_number=reg_number, name=name,
                                action="создан")
            self.counterparties[reg_number] = row
        return self.counterparties[reg_number]

    def load_projects(self) -> None:
        for name, entry in self.project_map.items():
            found = projects.project_ids_by_code([entry["code"]]).get(entry["code"])
            action = "найден"
            if not found:
                members = [entry["manager_user_id"]] if entry["manager_user_id"] else []
                found = projects.create_project(
                    code=entry["code"], name=name, country_code=entry["country"],
                    actor_id=self.actor_id, manager_user_id=entry["manager_user_id"],
                    member_ids=members)
                action = "создан"
            self.project_by_admin[name] = found
            self.report.add("Проекты", admin_id="", project_name=name,
                            project_code=entry["code"], action=action)

    def book_limits(self) -> dict[str, dict[str, Decimal]]:
        """``{администратор: {статья: лимит}}`` с листа «Бюджет»: программы
        одной статьи складываются; не KZT — в отчёт без переноса (D-06)."""
        out: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
        for row in self.budget:
            if row.currency != "KZT":
                self.report.add("Не перенесено", kind="бюджет", old_id=row.excel_row,
                                reason=f"«{row.administrator}» {row.program_code}: валюта "
                                       f"{row.currency} — лимиты модуля в KZT")
                continue
            article = self.article_map[(row.administrator, row.program_code)]
            out[row.administrator][article["id"]] += row.limit
        return out

    def load_budgets(self) -> None:
        """Нет бюджета — черновик для ФД (D-B62-2); есть — сравнение лимитов,
        расхождения в отчёт (D-B62-1)."""
        for admin, limits in self.book_limits().items():
            project_id = self.project_by_admin[admin]
            code = self.project_map[admin]["code"]
            budget = Budget.objects.filter(project_id=project_id).first()
            if budget is None:
                lines = [{"article_id": article, "limit_amount": amount}
                         for article, amount in limits.items() if amount > 0]
                if not lines:
                    continue
                try:
                    budget = budgets.create(self.actor, project_id=project_id, lines=lines)
                except DomainError as exc:
                    raise MigrationStop(f"Бюджет проекта {code}: {exc.message}") from exc
                self.report.add("Бюджеты", admin_id="", project_code=code, years="книга",
                                number=budget.number,
                                status="черновик — утвердите и запустите импорт снова")
                continue
            version = budget.active_version or budget.versions.order_by("version_no").first()
            have = {str(line.article_id): line.limit_amount for line in version.lines.all()}
            for article, amount in limits.items():
                if have.get(article, ZERO) != amount:
                    self.report.add("Расхождения с книгой", what="лимит статьи",
                                    key=f"{code} / {article}", book=amount,
                                    module=have.get(article, ZERO))
        for admin, project_id in self.project_by_admin.items():
            budget = Budget.objects.filter(project_id=project_id).first()
            if budget is not None and budget.status == BudgetStatus.APPROVED:
                self.approved.add(project_id)

    # ── договоры ──────────────────────────────────────────────────────

    @staticmethod
    def no_lark_key(row: RegistryRow) -> str:
        """Договор без LARK опознаётся администратором, номером и датой —
        хэшем: названия администраторов длинные, а ключ связи — до 64."""
        raw = "\x1f".join([row.administrator, row.number, str(row.signed_date or "")])
        return "nolark:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _known(self, key_type: str, key: str) -> MigrationLink | None:
        return MigrationLink.objects.filter(source_type=key_type, source_id=key).first()

    def _skip_unapproved(self, project_id: str, kind: str, key) -> bool:
        if project_id in self.approved:
            return False
        self.report.add("Не перенесено", kind=kind, old_id=key,
                        reason="бюджет проекта не утверждён — утвердите и запустите импорт снова")
        return True

    def load_agreements(self) -> None:
        paid_by_lark: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for op in self.operations:
            if op.kind == KIND_BY_AGREEMENT and op.agreement_lark:
                paid_by_lark[op.agreement_lark] += op.amount
        for row in self.registry:
            key = row.external_id or self.no_lark_key(row)
            known = self._known(AGREEMENT_KEY, key)
            if known is not None:
                if known.target_type == "bpp.agreement":
                    agr = Agreement.objects.filter(pk=known.target_id).first()
                    if agr and not agr.is_open and agr.amount != row.amount:
                        self.report.add("Расхождения с книгой", what="сумма договора",
                                        key=f"{agr.number} ({row.number})", book=row.amount,
                                        module=agr.amount)
                continue
            project_id = self.project_by_admin[row.administrator]
            if self._skip_unapproved(project_id, "договор", row.number):
                continue
            is_open = row.contract_type == "open"
            if not is_open and not row.has_amount:
                self.report.add("Не перенесено", kind="договор", old_id=row.number,
                                reason="стандартный договор без суммы")
                continue
            article = self.article_map[(row.administrator, row.program_code)]
            agreement_type = AgreementType.GOODS if row.kind == "goods" else AgreementType.WORKS
            reserve = max(paid_by_lark[row.external_id], CENT) if is_open else row.amount
            items = self.tech_request(
                project_id=project_id, article=article, author_id=self.actor_id,
                purpose=f"Импорт договора {row.number} из книги CashFlow",
                purchase_type=agreement_type,
                items=[(row.name or row.number or "Предмет договора",
                        self.uom("", kind="договор", old_id=row.number), Decimal("1"), reserve)],
                source=(AGREEMENT_KEY + ".request", key))
            vat = calc.vat_for("KZ", row.signed_date or self.today)
            amount = None if is_open else row.amount
            agr = Agreement.objects.create(
                number=next_number("ДГ"), ext_number=row.number[:50], ext_date=row.signed_date,
                name=row.name[:500], project_id=project_id, article_id=article["id"],
                counterparty=self.counterparty(row.bin_iin, row.counterparty),
                agreement_type=agreement_type, is_open=is_open, amount=amount,
                currency_code="KZT", with_vat=True, vat_rate=vat.rate, vat_source=vat.source,
                vat_amount=calc.vat_amount(amount, vat.rate) if amount is not None else None,
                status=AgreementStatus.ACTIVE, approval_state="approved",
                author_id=self.actor_id, initiator_role=items[0].request.initiator_role,
                counterparty_confirmed=True, is_migrated=True,
                created_by=self.actor_id, updated_by=self.actor_id)
            for item in items:
                AgreementItem.objects.create(agreement=agr, request_item=item, qty=item.qty,
                                             amount=None if is_open else item.amount,
                                             created_by=self.actor_id, updated_by=self.actor_id)
            audit.record(agr, "migrated", actor_id=self.actor_id,
                         changes={"source": f"cashflow:{key}", "old_number": row.number})
            links.link(AGREEMENT_KEY, key, "bpp.agreement", agr.pk)
            self.report.add("Документы", kind="договор", old_id=key, old_number=row.number,
                            new_number=agr.number, status=agr.get_status_display())

    # ── операции ──────────────────────────────────────────────────────

    def _mark_paid(self, inv, op: OperationRow) -> None:
        PaymentMark.objects.create(invoice=inv, amount=op.amount,
                                   pay_date=op.document_date or self.today,
                                   marked_by_id=self.actor_id, created_by=self.actor_id,
                                   updated_by=self.actor_id)

    def load_operations(self) -> None:
        for op in self.operations:
            if self._known(OPERATION_KEY, op.fingerprint):
                continue
            if op.kind == KIND_BY_AGREEMENT:
                self._by_agreement(op)
            else:
                self._without_agreement(op)

    def _by_agreement(self, op: OperationRow) -> None:
        known = self._known(AGREEMENT_KEY, op.agreement_lark) if op.agreement_lark else None
        if known is None or known.target_type != "bpp.agreement":
            if known is not None:
                reason = "договор закрыт — учтён в сальдо переноса"
            elif op.agreement_lark in {row.external_id for row in self.registry}:
                # Договор в книге есть, но не загружен: ждёт утверждения бюджета.
                reason = "бюджет проекта не утверждён — утвердите и запустите импорт снова"
            else:
                reason = f"договор LARK {op.agreement_lark or '—'} не загружен"
            self.report.add("Не перенесено", kind="операция по договору",
                            old_id=op.excel_row, reason=reason)
            return
        agr = Agreement.objects.get(pk=known.target_id)
        if self._skip_unapproved(str(agr.project_id), "операция по договору", op.excel_row):
            return
        items = [item.request_item for item in agr.items.select_related("request_item")
                 .order_by("request_item__line_no")]
        inv = self._invoice(
            basis=InvoiceBasis.CONTRACT, agreement=agr, project_id=str(agr.project_id),
            article_id=str(agr.article_id), counterparty=agr.counterparty, amount=op.amount,
            status=InvoiceStatus.PAID, author_id=self.actor_id, role=agr.initiator_role,
            purchase_type=agr.agreement_type, is_advance=False, ext_date=op.document_date,
            comment=f"Импорт из книги CashFlow: {op.goods}", lines=self.split(op.amount, items),
            source=(OPERATION_KEY, op.fingerprint))
        self._mark_paid(inv, op)
        self.report.add("Документы", kind="операция по договору", old_id=op.excel_row,
                        old_number=agr.ext_number, new_number=inv.number,
                        status=inv.get_status_display())

    def _without_agreement(self, op: OperationRow) -> None:
        project_id = self.project_by_admin.get(op.administrator)
        article = self.article_map.get((op.administrator, op.program_code))
        if project_id is None or article is None:
            self.report.add("Не перенесено", kind="операция без договора", old_id=op.excel_row,
                            reason="администратор или программа не в карте")
            return
        if self._skip_unapproved(project_id, "операция без договора", op.excel_row):
            return
        items = self.tech_request(
            project_id=project_id, article=article, author_id=self.actor_id,
            purpose=f"Импорт счёта «{op.goods}» из книги CashFlow", purchase_type="",
            items=[(op.goods or "Счёт без договора",
                    self.uom("", kind="операция", old_id=op.excel_row), Decimal("1"),
                    op.amount)],
            source=(OPERATION_KEY + ".request", op.fingerprint))
        inv = self._invoice(
            basis=InvoiceBasis.NO_CONTRACT, agreement=None, project_id=project_id,
            article_id=article["id"], counterparty=self.counterparty(op.bin_iin, op.supplier)
            if op.bin_iin else None, amount=op.amount, status=InvoiceStatus.PAID,
            author_id=self.actor_id, role=items[0].request.initiator_role, purchase_type="",
            is_advance=False, ext_date=op.document_date,
            comment=f"Импорт из книги CashFlow: {op.goods}",
            lines=[(items[0], Decimal("1"), op.amount)], source=(OPERATION_KEY, op.fingerprint))
        self._mark_paid(inv, op)
        self.report.add("Документы", kind="операция без договора", old_id=op.excel_row,
                        old_number="", new_number=inv.number, status=inv.get_status_display())

    def run(self) -> "CashflowLoader":
        self.load_projects()
        self.load_budgets()
        self.load_agreements()
        self.load_operations()
        return self
