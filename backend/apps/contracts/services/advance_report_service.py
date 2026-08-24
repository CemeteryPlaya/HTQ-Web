"""Авансовые отчёты по заявкам на подотчётные средства."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404

from apps.contracts.models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvanceReport,
)
from apps.media_files import interface as media
from apps.signoff import interface as signoff


ZERO = Decimal("0.00")
_RELATED = (
    "accountable_funds_request__budget_line__budget__administrator",
    "accountable_funds_request__budget_line__program",
    "accountable_funds_request__administrator",
    "accountable_funds_request__program",
)


class AdvanceReportRuleViolation(Exception):
    """Нарушено правило оформления авансового отчёта."""


def get_advance_report_or_404(report_id: int, *, lock: bool = False) -> AdvanceReport:
    # The request still has nullable legacy relations. PostgreSQL refuses to
    # lock nullable sides of outer joins, so lock the report row alone.
    query = AdvanceReport.objects.select_for_update() if lock \
        else AdvanceReport.objects.select_related(*_RELATED)
    report = query.filter(pk=report_id).first()
    if report is None:
        raise Http404("Авансовый отчёт не найден")
    return report


def approved_amount_for_request(request_id: int) -> Decimal:
    return (AdvanceReport.objects
            .filter(accountable_funds_request_id=request_id,
                    approval_state=signoff.ApprovalState.APPROVED)
            .aggregate(total=Sum("amount"))["total"] or ZERO)


def totals_for_request(request: AccountableFundsRequest) -> dict:
    reported = approved_amount_for_request(request.pk)
    return {"reported_amount": reported, "remaining_amount": request.amount - reported}


def _reserved_amount_for_request(request_id: int, *, include_report_id: int | None = None) -> Decimal:
    """Одобренные и уже отправленные отчёты занимают остаток на время Signoff."""
    query = AdvanceReport.objects.filter(
        accountable_funds_request_id=request_id,
        approval_state__in=(signoff.ApprovalState.APPROVED, signoff.ApprovalState.PENDING),
    )
    if include_report_id is not None:
        query = query.exclude(pk=include_report_id)
    return query.aggregate(total=Sum("amount"))["total"] or ZERO


def _ensure_request_open(request: AccountableFundsRequest) -> None:
    if not request.accounting_paid or request.status != AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT:
        raise AdvanceReportRuleViolation(
            "Авансовый отчёт можно добавить только после выдачи средств бухгалтерией"
        )


def _ensure_owner(request: AccountableFundsRequest, actor_id: int, is_elevated: bool) -> None:
    if not is_elevated and request.accountable_user_id != actor_id:
        raise PermissionError("Добавлять и отправлять отчёты может только инициатор заявки")


def _ensure_capacity(request: AccountableFundsRequest, amount: Decimal,
                     *, exclude_report_id: int | None = None) -> None:
    remaining = request.amount - _reserved_amount_for_request(
        request.pk, include_report_id=exclude_report_id,
    )
    if amount > remaining:
        raise AdvanceReportRuleViolation(
            f"Сумма отчёта превышает остаток подотчётных средств: доступно {remaining}"
        )


def serialize_advance_report(report: AdvanceReport) -> dict:
    request = report.accountable_funds_request
    line = request.budget_line
    return {
        "id": report.pk,
        "accountable_funds_request_id": request.pk,
        "expense_name": report.expense_name,
        "amount": report.amount,
        "currency": line.budget.currency if line else "",
        "file_id": report.file_id,
        "approval_state": report.approval_state,
        "created_by": report.created_by,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def list_advance_reports(*, request_id: int) -> list[AdvanceReport]:
    return list(AdvanceReport.objects.filter(accountable_funds_request_id=request_id)
                .select_related(*_RELATED))


@transaction.atomic
def create_advance_report(*, request_id: int, expense_name: str, amount: Decimal,
                          data: bytes, filename: str, mime: str, actor_id: int,
                          is_elevated: bool = False) -> AdvanceReport:
    request = (AccountableFundsRequest.objects.select_for_update()
               .filter(pk=request_id).first())
    if request is None:
        raise Http404("Заявка на подотчётные средства не найдена")
    _ensure_request_open(request)
    _ensure_owner(request, actor_id, is_elevated)
    if amount > request.amount:
        raise AdvanceReportRuleViolation("Сумма отчёта превышает сумму заявки")
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=actor_id)
    return AdvanceReport.objects.create(
        accountable_funds_request=request,
        expense_name=expense_name.strip(), amount=amount, file_id=str(stored["id"]),
        created_by=actor_id,
    )


@transaction.atomic
def submit_for_approval(report_id: int, *, actor_id: int, is_elevated: bool = False) -> dict:
    report = get_advance_report_or_404(report_id, lock=True)
    request = (AccountableFundsRequest.objects.select_for_update()
               .filter(pk=report.accountable_funds_request_id).first())
    assert request is not None  # protected FK
    _ensure_request_open(request)
    _ensure_owner(request, actor_id, is_elevated)
    report.assert_editable()
    _ensure_capacity(request, report.amount, exclude_report_id=report.pk)
    return signoff.start_process(
        subject_type=AdvanceReport.SIGNOFF_SUBJECT_TYPE,
        subject_id=report.pk,
        initiator_id=actor_id,
        enrich=True,
    )


@transaction.atomic
def close_parent_if_fully_reported(report_id: int) -> None:
    """Вызывается Signoff после одобрения отчёта."""
    report = get_advance_report_or_404(report_id, lock=True)
    request = (AccountableFundsRequest.objects.select_for_update()
               .filter(pk=report.accountable_funds_request_id).first())
    assert request is not None  # protected FK
    _ensure_request_open(request)
    # Signoff invokes callbacks immediately *before* it writes the final
    # approval_state on the subject. Count this report explicitly; the other
    # approved reports are already visible through the aggregate.
    reported = approved_amount_for_request(request.pk)
    if report.approval_state != signoff.ApprovalState.APPROVED:
        reported += report.amount
    remaining = request.amount - reported
    if remaining < ZERO:
        raise AdvanceReportRuleViolation("Одобренные отчёты превышают сумму заявки")
    if remaining == ZERO:
        request.status = AccountableFundsRequestStatus.CLOSED
        request.save(update_fields=["status", "updated_at"])


def file_url(report: AdvanceReport) -> str:
    return media.get_file_url(report.file_id)
