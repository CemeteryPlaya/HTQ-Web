"""Заявки на подотчётные средства и их короткий жизненный цикл."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.contracts.models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    BudgetLine,
)
from apps.contracts.services import budget_calc
from apps.signoff import interface as signoff


ACCOUNTING_PAYMENT_PERMISSION = "contracts.accountable_funds_request.mark_paid"

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AccountableFundsRequestStatus.DRAFT: frozenset({AccountableFundsRequestStatus.ON_REVIEW}),
    AccountableFundsRequestStatus.ON_REVIEW: frozenset({
        AccountableFundsRequestStatus.DRAFT,
        AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
    }),
    AccountableFundsRequestStatus.AWAITING_ACCOUNTING: frozenset({
        AccountableFundsRequestStatus.DRAFT,
        AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT,
    }),
    AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT: frozenset(),
}


class AccountableFundsRequestRuleViolation(Exception):
    """Нарушено правило жизненного цикла заявки на подотчётные средства."""


_RELATED = ("budget_line__budget__administrator", "budget_line__program", "administrator", "program")


def get_request_or_404(request_id: int, *, lock: bool = False) -> AccountableFundsRequest:
    if lock:
        # `budget_line` is nullable only for legacy rows. PostgreSQL cannot
        # lock the nullable side of its outer joins, so lock the request row
        # itself first and load display relations afterwards if needed.
        query = AccountableFundsRequest.objects.select_for_update()
    else:
        query = AccountableFundsRequest.objects.select_related(*_RELATED)
    request = query.filter(pk=request_id).first()
    if request is None:
        raise Http404("Заявка на подотчётные средства не найдена")
    return request


def serialize_request(request: AccountableFundsRequest) -> dict:
    line = request.budget_line
    administrator = line.budget.administrator if line else request.administrator
    program = line.program if line else request.program
    return {
        "id": request.pk,
        "budget_line_id": request.budget_line_id,
        "administrator_id": administrator.pk,
        "administrator_name": administrator.display_name,
        "program_id": program.pk,
        "program_name": program.display_name,
        "expense_item": program.expense_item,
        "period_year": line.budget.period_year if line else None,
        "currency": line.budget.currency if line else "",
        "amount": request.amount,
        "goal": request.goal,
        "status": request.status,
        "approval_state": request.approval_state,
        "accounting_paid": request.accounting_paid,
        "accounting_paid_by": request.accounting_paid_by,
        "accounting_paid_at": request.accounting_paid_at,
        "accountable_user_id": request.accountable_user_id,
        "created_by": request.created_by,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


def list_requests(*, administrator_id: int | None = None, program_id: int | None = None,
                  accountable_user_id: int | None = None):
    query = AccountableFundsRequest.objects.select_related(*_RELATED)
    if administrator_id is not None:
        query = query.filter(Q(budget_line__budget__administrator_id=administrator_id) |
                             Q(budget_line__isnull=True, administrator_id=administrator_id))
    if program_id is not None:
        query = query.filter(Q(budget_line__program_id=program_id) |
                             Q(budget_line__isnull=True, program_id=program_id))
    if accountable_user_id is not None:
        query = query.filter(accountable_user_id=accountable_user_id)
    return list(query)


@transaction.atomic
def create_request(*, budget_line_id: int, amount, goal: str,
                   created_by: int) -> AccountableFundsRequest:
    line = (BudgetLine.objects.select_for_update().select_related("budget__administrator", "program")
            .filter(pk=budget_line_id).first())
    if line is None or not line.budget.administrator.is_active:
        raise AccountableFundsRequestRuleViolation("Строка бюджета или администратор не найдены либо отключены")
    if not line.program.is_active:
        raise AccountableFundsRequestRuleViolation("Программа не найдена или отключена")
    budget_calc.check_capacity(line, amount)
    return AccountableFundsRequest.objects.create(
        budget_line=line,
        amount=amount,
        goal=goal.strip(),
        accountable_user_id=created_by,
        created_by=created_by,
    )


@transaction.atomic
def assign_budget_line(request_id: int, *, budget_line_id: int, actor_id: int,
                       is_elevated: bool = False) -> AccountableFundsRequest:
    """Однократно привязать запись первой версии к точной строке бюджета."""
    request = get_request_or_404(request_id, lock=True)
    if request.budget_line_id is not None:
        raise AccountableFundsRequestRuleViolation("Строка бюджета уже указана")
    if not is_elevated and request.created_by != actor_id:
        raise PermissionError("Указать строку бюджета может только инициатор заявки")
    line = (BudgetLine.objects.select_for_update().select_related("budget__administrator", "program")
            .filter(pk=budget_line_id).first())
    if line is None:
        raise Http404("Строка бюджета не найдена")
    if line.budget.administrator_id != request.administrator_id or line.program_id != request.program_id:
        raise AccountableFundsRequestRuleViolation(
            "Строка бюджета должна соответствовать администратору и программе заявки"
        )
    budget_calc.check_capacity(line, request.amount)
    request.budget_line = line
    request.save(update_fields=["budget_line", "updated_at"])
    return get_request_or_404(request.pk)


@transaction.atomic
def submit_for_approval(request_id: int, *, actor_id: int | None = None) -> dict:
    request = get_request_or_404(request_id, lock=True)
    if request.budget_line_id is None:
        raise AccountableFundsRequestRuleViolation(
            "Для ранее созданной заявки сначала укажите строку бюджета"
        )
    if request.status != AccountableFundsRequestStatus.DRAFT:
        raise AccountableFundsRequestRuleViolation(
            "На согласование можно отправить только заявку в статусе «Черновик»"
        )
    if request.approval_state not in signoff.ApprovalState.editable():
        request.assert_editable()
    budget_calc.check_capacity(request.budget_line, request.amount)
    return signoff.start_process(
        subject_type=AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE,
        subject_id=request.pk,
        initiator_id=actor_id,
        enrich=True,
    )


def change_status(request_id: int, new_status: str) -> AccountableFundsRequest:
    request = get_request_or_404(request_id)
    if new_status not in AccountableFundsRequestStatus.values:
        raise AccountableFundsRequestRuleViolation("Неизвестный статус заявки")
    if new_status == request.status:
        return request
    if new_status not in ALLOWED_TRANSITIONS[request.status]:
        raise AccountableFundsRequestRuleViolation("Переход статуса заявки не разрешён")
    request.status = new_status
    request.save(update_fields=["status", "updated_at"])
    return request


@transaction.atomic
def mark_accounting_paid(request_id: int, *, actor_id: int, is_elevated: bool = False) -> AccountableFundsRequest:
    request = get_request_or_404(request_id, lock=True)
    if request.budget_line_id is None:
        raise AccountableFundsRequestRuleViolation(
            "Для ранее созданной заявки сначала укажите строку бюджета"
        )
    if not request.is_approved or request.status != AccountableFundsRequestStatus.AWAITING_ACCOUNTING:
        raise AccountableFundsRequestRuleViolation(
            "Отметить оплату можно только после согласования заявки"
        )
    if request.accounting_paid:
        raise AccountableFundsRequestRuleViolation("Оплата уже отмечена бухгалтерией")
    if not is_elevated:
        from apps.hr import interface as hr
        if not hr.user_has_permission(actor_id, ACCOUNTING_PAYMENT_PERMISSION):
            raise PermissionError("Требуется роль «Бухгалтер»")
    request.accounting_paid = True
    request.accounting_paid_by = actor_id
    request.accounting_paid_at = timezone.now()
    request.status = AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT
    request.save(update_fields=[
        "accounting_paid", "accounting_paid_by", "accounting_paid_at", "status", "updated_at",
    ])
    return get_request_or_404(request.pk)
