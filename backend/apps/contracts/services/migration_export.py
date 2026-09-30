"""Выгрузка раздела для переноса в модуль БЗО (мастер-план, B6.1).

Команда ``bpp_migrate_contracts`` живёт в ``apps.bpp`` и моделей этой аппки
не видит (сторож изоляции), поэтому всё нужное ей отдаётся отсюда плоскими
словарями через ``interface.migration_snapshot``.

У каждого документа — поле ``committed``: сколько он занимает строки бюджета
по правилам ``budget_calc`` (``committed_map``). Сумма вкладов документов
строки обязана совпасть с ``committed_map`` по ней — это проверяет тест, и
на этом держится сверка остатков после переноса: вклад закрытых документов
уходит в сальдо статьи (D-B61-1), вклад открытых — в их новые документы.
Поэтому правила вклада повторяют ``committed_map`` буквально, включая его
особенности (оплаты открытого договора считаются и у договора-поступления).
"""

from __future__ import annotations

from decimal import Decimal

from .. import models as m
from . import budget_calc

ZERO = Decimal("0.00")

#: Платёжные документы договора: вид → (модель, поле файла документа).
PAYMENT_KINDS = {
    "advance_payment": (m.AdvancePayment, None),
    "contract_payment": (m.ContractPayment, "invoice_file_id"),
    "completion_act": (m.CompletionAct, "act_file_id"),
    "goods_invoice": (m.GoodsInvoice, "waybill_file_id"),
}


def _agreement_committed(agr: m.Agreement) -> Decimal:
    if (agr.status in budget_calc.COMMITTING_STATUSES
            and agr.direction == m.AgreementDirection.EXPENSE
            and agr.contract_type != m.AgreementType.FRAMEWORK):
        return agr.amount
    return ZERO


def _payment_committed(payment, agreement: m.Agreement) -> Decimal:
    if (agreement.contract_type == m.AgreementType.FRAMEWORK
            and payment.status in budget_calc.OPEN_AGREEMENT_SPENDING_STATUSES):
        return payment.amount
    return ZERO


def snapshot() -> dict:
    """Всё, что переносится, и вклад каждого документа в «занято»."""
    budgets = list(m.Budget.objects.prefetch_related("lines").order_by("id"))
    line_ids = [line.id for budget in budgets for line in budget.lines.all()]
    agreements = list(m.Agreement.objects.prefetch_related("items").order_by("created_at", "id"))
    agreement_by_id = {agr.id: agr for agr in agreements}

    payments = []
    for kind, (model, file_field) in PAYMENT_KINDS.items():
        for row in model.objects.order_by("created_at", "id"):
            agreement = agreement_by_id[row.agreement_id]
            payments.append({
                "kind": kind, "id": row.id, "agreement_id": row.agreement_id,
                "budget_line_id": agreement.budget_line_id, "amount": row.amount,
                "status": row.status, "approval_state": row.approval_state,
                "file_id": getattr(row, file_field) if file_field else None,
                "payment_order_file_id": row.payment_order_file_id,
                "posting_number": row.posting_number, "paid_by": row.paid_by,
                "paid_at": row.paid_at, "document_date": getattr(row, "document_date", None),
                "created_by": row.created_by, "created_at": row.created_at,
                "committed": _payment_committed(row, agreement),
            })

    accountable = []
    for req in (m.AccountableFundsRequest.objects.prefetch_related("advance_reports")
                .order_by("created_at", "id")):
        committing = (req.budget_line_id is not None
                      and req.status in budget_calc.ACCOUNTABLE_FUNDS_COMMITTING_STATUSES)
        accountable.append({
            "id": req.id, "budget_line_id": req.budget_line_id,
            "administrator_id": req.administrator_id, "program_id": req.program_id,
            "amount": req.amount, "goal": req.goal, "status": req.status,
            "approval_state": req.approval_state, "accounting_paid": req.accounting_paid,
            "accounting_paid_by": req.accounting_paid_by,
            "accounting_paid_at": req.accounting_paid_at,
            "accountable_user_id": req.accountable_user_id, "created_by": req.created_by,
            "created_at": req.created_at,
            "committed": req.amount if committing else ZERO,
            "reports": [{
                "id": report.id, "expense_name": report.expense_name, "amount": report.amount,
                "file_id": report.file_id, "approval_state": report.approval_state,
                "created_by": report.created_by, "created_at": report.created_at,
            } for report in sorted(req.advance_reports.all(), key=lambda r: (r.created_at, r.id))],
        })

    return {
        "countries": list(m.Country.objects.order_by("id").values("id", "name", "iso_code")),
        "programs": list(m.Program.objects.order_by("id").values(
            "id", "code", "name", "expense_item", "is_active")),
        "administrators": list(m.Administrator.objects.order_by("id").values(
            "id", "project_name", "country_id", "project_id", "user_id", "is_active")),
        "budgets": [{
            "id": budget.id, "administrator_id": budget.administrator_id,
            "period_year": budget.period_year, "currency": budget.currency,
            "status": budget.status, "approval_state": budget.approval_state,
            "lines": [{"id": line.id, "program_id": line.program_id, "amount": line.amount}
                      for line in sorted(budget.lines.all(), key=lambda line: line.id)],
        } for budget in budgets],
        "counterparties": list(m.Counterparty.objects.order_by("id").values(
            "id", "bin_iin", "name", "vat", "contact_name", "phone", "email", "address",
            "country_id", "status")),
        "agreements": [{
            "id": agr.id, "number": agr.number, "name": agr.name,
            "budget_line_id": agr.budget_line_id, "counterparty_id": agr.counterparty_id,
            "direction": agr.direction, "kind": agr.kind, "contract_type": agr.contract_type,
            "status": agr.status, "approval_state": agr.approval_state,
            "has_vat": agr.has_vat, "vat_rate": agr.vat_rate, "vat_amount": agr.vat_amount,
            "amount": agr.amount, "currency": agr.currency, "start_date": agr.start_date,
            "end_date": agr.end_date, "signed_date": agr.signed_date, "subject": agr.subject,
            "file_id": agr.file_id, "manager_user_id": agr.manager_user_id,
            "created_by": agr.created_by, "created_at": agr.created_at,
            "committed": _agreement_committed(agr),
            "items": [{"line_no": item.line_no, "name": item.name, "unit": item.unit,
                       "quantity": item.quantity, "amount": item.amount}
                      for item in sorted(agr.items.all(), key=lambda item: item.line_no)],
        } for agr in agreements],
        "invoices": [{
            "id": inv.id, "name": inv.name, "note": inv.note,
            "budget_line_id": inv.budget_line_id, "counterparty_id": inv.counterparty_id,
            "amount": inv.amount, "currency": inv.currency, "file_id": inv.file_id,
            "status": inv.status, "approval_state": inv.approval_state,
            "document_date": inv.document_date, "created_by": inv.created_by,
            "created_at": inv.created_at,
            "committed": (inv.amount if inv.status in budget_calc.INVOICE_COMMITTING_STATUSES
                          else ZERO),
        } for inv in m.Invoice.objects.order_by("created_at", "id")],
        "payments": payments,
        "accountable": accountable,
        "committed_by_line": budget_calc.committed_map(line_ids),
    }


def revoke(subject_type: str, ids) -> list[int]:
    """Отозвать идущие согласования документов перед переносом (D-B61-2):
    движок отменяет процесс, колбэк раздела возвращает документ в черновик.
    Возвращает ключи, у которых процесс был и отозван."""
    from apps.signoff import interface as signoff

    revoked = []
    for subject_id in ids:
        process = signoff.get_process_for(subject_type, subject_id)
        if process and process.get("state") == "pending":
            signoff.cancel_process(process_id=process["id"], actor_id=None)
            revoked.append(subject_id)
    return revoked
