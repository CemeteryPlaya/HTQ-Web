"""Personal action queue for the contracts domain.

This deliberately does not include approval decisions: those belong to the
``signoff`` application and remain on its own page.  It answers a narrower
question: which contracts records can the current user progress right now?
"""

from __future__ import annotations

from decimal import Decimal

from apps.contracts.models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvancePayment,
    AdvancePaymentStatus,
    AdvanceReport,
    Agreement,
    AgreementStatus,
    CompletionAct,
    ContractPayment,
    Invoice,
    InvoiceStatus,
)
from apps.contracts.services.accountable_funds_request_service import (
    ACCOUNTING_PAYMENT_PERMISSION,
)
from apps.contracts.services.advance_payment_service import (
    ACCOUNT_PAYMENT_PERMISSION as ADVANCE_PAYMENT_PERMISSION,
)
from apps.contracts.services.contract_payment_service import (
    ACCOUNT_PAYMENT_PERMISSION as CONTRACT_PAYMENT_PERMISSION,
)
from apps.hr import interface as hr
from apps.signoff import interface as signoff


def _item(*, document_type: str, action: str, action_label: str, title: str,
          url: str, created_at, amount: Decimal | None = None,
          currency: str = "") -> dict:
    return {
        "document_type": document_type,
        "action": action,
        "action_label": action_label,
        "title": title,
        "url": url,
        "amount": amount,
        "currency": currency,
        "created_at": created_at,
    }


def _submission_action(approval_state: str) -> tuple[str, str]:
    if approval_state == signoff.ApprovalState.REWORK:
        return "rework", "Доработать и отправить"
    return "submit", "Отправить на согласование"


def _request_currency(request: AccountableFundsRequest) -> str:
    if request.budget_line_id is None:
        return ""
    return request.budget_line.budget.currency


def _own_drafts(user_id: int) -> list[dict]:
    """Documents owned by the user which are editable and ready to progress."""
    items: list[dict] = []

    for agreement in Agreement.objects.filter(
        created_by=user_id, status=AgreementStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(agreement.approval_state)
        items.append(_item(
            document_type="agreement", action=action, action_label=label,
            title=f"Договор {agreement.number} — {agreement.name}",
            url=f"/contracts/agreements/{agreement.pk}", amount=agreement.amount,
            currency=agreement.currency, created_at=agreement.updated_at,
        ))

    for invoice in Invoice.objects.filter(
        created_by=user_id, status=InvoiceStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(invoice.approval_state)
        items.append(_item(
            document_type="invoice", action=action, action_label=label,
            title=f"Счёт — {invoice.name}", url=f"/contracts/invoices/{invoice.pk}",
            amount=invoice.amount, currency=invoice.currency, created_at=invoice.updated_at,
        ))

    for payment in AdvancePayment.objects.select_related("agreement").filter(
        created_by=user_id, status=AdvancePaymentStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(payment.approval_state)
        items.append(_item(
            document_type="advance_payment", action=action, action_label=label,
            title=f"Предоплата по договору {payment.agreement.number}",
            url=f"/contracts/advance-payments/{payment.pk}", amount=payment.amount,
            currency=payment.agreement.currency, created_at=payment.updated_at,
        ))

    for request in AccountableFundsRequest.objects.select_related("budget_line__budget").filter(
        created_by=user_id, status=AccountableFundsRequestStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(request.approval_state)
        items.append(_item(
            document_type="accountable_funds_request", action=action, action_label=label,
            title=f"Заявка на подотчётные средства — {request.goal}",
            url=f"/contracts/accountable-funds-requests/{request.pk}", amount=request.amount,
            currency=_request_currency(request), created_at=request.updated_at,
        ))

    for payment in ContractPayment.objects.select_related("agreement").filter(
        created_by=user_id, status=AdvancePaymentStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(payment.approval_state)
        items.append(_item(
            document_type="contract_payment", action=action, action_label=label,
            title=f"Оплата по договору {payment.agreement.number}",
            url=f"/contracts/contract-payments/{payment.pk}", amount=payment.amount,
            currency=payment.agreement.currency, created_at=payment.updated_at,
        ))

    for act in CompletionAct.objects.select_related("agreement").filter(
        created_by=user_id, status=AdvancePaymentStatus.DRAFT,
        approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(act.approval_state)
        items.append(_item(
            document_type="completion_act", action=action, action_label=label,
            title=f"Акт выполненных работ по договору {act.agreement.number}",
            url=f"/contracts/completion-acts/{act.pk}", amount=act.amount,
            currency=act.agreement.currency, created_at=act.updated_at,
        ))

    for report in AdvanceReport.objects.select_related("accountable_funds_request").filter(
        created_by=user_id, approval_state__in=(signoff.ApprovalState.DRAFT, signoff.ApprovalState.REWORK),
    ):
        action, label = _submission_action(report.approval_state)
        items.append(_item(
            document_type="advance_report", action=action, action_label=label,
            title=f"Авансовый отчёт — {report.expense_name}",
            url=f"/contracts/accountable-funds-requests/{report.accountable_funds_request_id}", amount=report.amount,
            created_at=report.updated_at,
        ))

    return items


def _accounting_tasks(user_id: int, *, is_elevated: bool) -> list[dict]:
    if is_elevated:
        can_record_advance = can_record_contract = can_mark_request_paid = True
    else:
        can_record_advance = hr.user_has_permission(user_id, ADVANCE_PAYMENT_PERMISSION)
        can_record_contract = hr.user_has_permission(user_id, CONTRACT_PAYMENT_PERMISSION)
        can_mark_request_paid = hr.user_has_permission(user_id, ACCOUNTING_PAYMENT_PERMISSION)

    items: list[dict] = []
    if can_record_advance:
        for payment in AdvancePayment.objects.select_related("agreement").filter(
            status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        ):
            items.append(_item(
                document_type="advance_payment", action="record_payment",
                action_label="Оформить оплату",
                title=f"Предоплата по договору {payment.agreement.number}",
                url=f"/contracts/advance-payments/{payment.pk}", amount=payment.amount,
                currency=payment.agreement.currency, created_at=payment.updated_at,
            ))

    if can_record_contract:
        for payment in ContractPayment.objects.select_related("agreement").filter(
            status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        ):
            items.append(_item(
                document_type="contract_payment", action="record_payment",
                action_label="Оформить оплату",
                title=f"Оплата по договору {payment.agreement.number}",
                url=f"/contracts/contract-payments/{payment.pk}", amount=payment.amount,
                currency=payment.agreement.currency, created_at=payment.updated_at,
            ))
        for act in CompletionAct.objects.select_related("agreement").filter(
            status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        ):
            items.append(_item(
                document_type="completion_act", action="record_payment",
                action_label="Оформить оплату",
                title=f"Акт выполненных работ по договору {act.agreement.number}",
                url=f"/contracts/completion-acts/{act.pk}", amount=act.amount,
                currency=act.agreement.currency, created_at=act.updated_at,
            ))

    if can_mark_request_paid:
        for request in AccountableFundsRequest.objects.select_related("budget_line__budget").filter(
            status=AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
            accounting_paid=False,
        ):
            items.append(_item(
                document_type="accountable_funds_request", action="mark_paid",
                action_label="Подтвердить оплату",
                title=f"Заявка на подотчётные средства — {request.goal}",
                url=f"/contracts/accountable-funds-requests/{request.pk}", amount=request.amount,
                currency=_request_currency(request), created_at=request.updated_at,
            ))
    return items


def _advance_report_tasks(user_id: int) -> list[dict]:
    return [
        _item(
            document_type="accountable_funds_request", action="submit_advance_report",
            action_label="Добавить авансовый отчёт",
            title=f"Заявка на подотчётные средства — {request.goal}",
            url=f"/contracts/accountable-funds-requests/{request.pk}", amount=request.amount,
            currency=_request_currency(request), created_at=request.updated_at,
        )
        for request in AccountableFundsRequest.objects.select_related("budget_line__budget").filter(
            accountable_user_id=user_id,
            status=AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT,
        )
    ]


def list_my_actions(*, user_id: int, is_elevated: bool = False) -> list[dict]:
    """Return only current contracts actions, newest first."""
    items = _own_drafts(user_id)
    items.extend(_accounting_tasks(user_id, is_elevated=is_elevated))
    items.extend(_advance_report_tasks(user_id))
    return sorted(items, key=lambda item: item["created_at"], reverse=True)
