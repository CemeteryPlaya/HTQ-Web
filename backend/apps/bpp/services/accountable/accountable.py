"""Подотчётные средства: заявка, выдача, авансовые отчёты (задача B4.1, Q-B07).

Логика перенесена из ``contracts`` без изменений по сути:

- заявку заводит сотрудник на себя (подотчётное лицо = автор), сумма
  сверяется с остатком статьи бюджета проекта — при сохранении и при
  отправке, под блокировкой строки бюджета;
- согласование — движок ``signoff`` (тип ``bpp.accountable_funds_request``,
  маршрут настраивает администратор);
- после согласования бухгалтер отмечает выдачу (узел
  ``bpp.accountable.payment``) — заявка ждёт авансовых отчётов;
- авансовый отчёт — трата с подтверждающим файлом, тоже через ``signoff``
  (``bpp.advance_report``); одобренные отчёты, покрывшие сумму, закрывают
  заявку.

Отличия от ``contracts``: источник средств — статья бюджета проекта, а не
строка годового бюджета; ошибки — конверт модуля с кодами; у заявки есть
номер ``ПО-ГГГГ-NNNNNN``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bpp.models import (
    AccountableFundsRequest,
    AccountableStatus,
    AdvanceReport,
)
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.money import fmt, money
from apps.project import interface as projects
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

REQUEST_SUBJECT = AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE
REPORT_SUBJECT = AdvanceReport.SIGNOFF_SUBJECT_TYPE
ZERO = Decimal("0.00")
REPORT_FILE = "advance_report"


# ── права ───────────────────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def sees_all(actor: Actor) -> bool:
    """ФД и бухгалтер видят все заявки, сотрудник — свои (как ``requests.sees_all``:
    у просмотра без права создавать)."""
    return actor.can("bpp.accountable", "view") and not actor.can("bpp.accountable", "create")


def can_view(actor: Actor, req: AccountableFundsRequest) -> bool:
    return (req.accountable_user_id == actor.user_id or sees_all(actor)
            or signoff.is_participant(actor.user_id, REQUEST_SUBJECT, str(req.pk)))


def get_visible(actor: Actor, request_id) -> AccountableFundsRequest:
    req = AccountableFundsRequest.objects.filter(pk=request_id).first()
    if req is None or not can_view(actor, req):
        raise DomainError("E-NOT-FOUND", "Заявка на подотчётные средства не найдена.",
                          status=404)
    return req


def _lock(request_id) -> AccountableFundsRequest:
    req = AccountableFundsRequest.objects.select_for_update().filter(pk=request_id).first()
    if req is None:
        raise DomainError("E-NOT-FOUND", "Заявка на подотчётные средства не найдена.",
                          status=404)
    return req


def _require_owner(actor: Actor, req: AccountableFundsRequest, action: str) -> None:
    if req.accountable_user_id != actor.user_id:
        raise _deny(f"{action} может только подотчётное лицо — автор заявки {req.number}.")


def _require_status(req: AccountableFundsRequest, statuses, action: str) -> None:
    if req.status not in statuses:
        raise DomainError(
            "E-STATE-01", f"Заявка {req.number} в статусе «{req.get_status_display()}» — "
                          f"{action} сейчас недоступно.", status=409)


def allowed_actions(actor: Actor, req: AccountableFundsRequest) -> list[str]:
    owner = req.accountable_user_id == actor.user_id
    actions = []
    if owner and req.status == AccountableStatus.DRAFT and req.is_editable:
        actions += ["save", "submit", "delete"]
    if (req.status == AccountableStatus.AWAITING_ACCOUNTING
            and actor.can("bpp.accountable.payment", "edit")):
        actions.append("mark_paid")
    if owner and req.status == AccountableStatus.AWAITING_REPORT:
        actions.append("add_report")
    return actions


# ── остаток ─────────────────────────────────────────────────────────────

def _check_budget(req: AccountableFundsRequest, *, lock: bool) -> None:
    """Сумма ≤ остатка статьи без самой заявки (как ``check_capacity`` в
    contracts). При отправке — под блокировкой строки бюджета."""
    if lock:
        budget_balance.lock_line(req.project_id, req.article_id)
    figures = budget_balance.balance(req.project_id, req.article_id,
                                     exclude_accountable_id=req.pk)
    if req.amount > figures["available"]:
        over = req.amount - figures["available"]
        raise DomainError(
            "E-BUD-01",
            f"Сумма заявки {fmt(req.amount, req.currency)} превышает доступный остаток "
            f"статьи «{budget_balance.article_name(req.article_id)}» "
            f"({fmt(figures['available'], req.currency)}) на {fmt(over, req.currency)}. "
            f"Уменьшите сумму или обратитесь к финансовому директору за корректировкой лимита.",
            fields=[{"field": "amount", "message": "Сумма превышает остаток",
                     "available": str(figures["available"]), "over": str(over)}])


def _check_source(actor: Actor, project_id, article_id) -> str:
    brief = projects.project_brief([str(project_id)]).get(str(project_id))
    if brief is None or brief["status"] != "active":
        raise DomainError("E-PRJ-03", "Проект не найден или не активен.",
                          fields=[{"field": "project_id", "message": "Проект не активен"}])
    if not actor.sees_project(project_id):
        raise _deny(f"Вы не работаете с проектом {brief['code']}.")
    budget = budget_balance.approved_budget(project_id)  # E-BUD-02
    budget_balance.active_line(project_id, article_id)   # E-BUD-03
    return budget.currency


# ── заявка ──────────────────────────────────────────────────────────────

@transaction.atomic
def create(actor: Actor, *, project_id, article_id, amount, goal: str) -> AccountableFundsRequest:
    if not actor.can("bpp.accountable", "create"):
        raise _deny("У вас нет права заводить заявки на подотчётные средства.")
    currency = _check_source(actor, project_id, article_id)
    goal = (goal or "").strip()
    if not goal:
        raise DomainError("E-VAL-01", "Укажите цель подотчётных средств.",
                          fields=[{"field": "goal", "message": "Не заполнено"}])
    req = AccountableFundsRequest(
        number=next_number("ПО"), project_id=project_id, article_id=article_id,
        amount=money(amount), currency=currency, goal=goal,
        accountable_user_id=actor.user_id, created_by=actor.user_id, updated_by=actor.user_id)
    if req.amount <= 0:
        raise DomainError("E-VAL-01", "Сумма должна быть больше нуля.",
                          fields=[{"field": "amount", "message": "Сумма > 0"}])
    _check_budget(req, lock=False)
    req.save()
    audit.record(req, "created", actor_id=actor.user_id,
                 changes={"amount": str(req.amount), "goal": req.goal})
    return req


@transaction.atomic
def update_draft(actor: Actor, request_id, *, expected_version, data: dict):
    req = _lock(request_id)
    req.assert_editable()
    _require_owner(actor, req, "Править заявку")
    _require_status(req, (AccountableStatus.DRAFT,), "правка")
    check_version(req, expected_version)
    before = {"amount": str(req.amount), "goal": req.goal, "article_id": str(req.article_id)}
    if data.get("project_id") or data.get("article_id"):
        project_id = data.get("project_id") or req.project_id
        article_id = data.get("article_id") or req.article_id
        _check_source(actor, project_id, article_id)
        req.project_id, req.article_id = project_id, article_id
    if data.get("amount") is not None:
        req.amount = money(data["amount"])
    if data.get("goal") is not None:
        req.goal = data["goal"].strip()
    _check_budget(req, lock=False)
    req.version += 1
    req.updated_by = actor.user_id
    req.save()
    audit.record(req, "updated", actor_id=actor.user_id,
                 changes={"before": before, "after": {"amount": str(req.amount),
                                                      "goal": req.goal,
                                                      "article_id": str(req.article_id)}})
    return req


@transaction.atomic
def delete_draft(actor: Actor, request_id, *, expected_version) -> None:
    req = _lock(request_id)
    req.assert_editable()
    _require_owner(actor, req, "Удалить заявку")
    _require_status(req, (AccountableStatus.DRAFT,), "удаление")
    check_version(req, expected_version)
    audit.record(req, "deleted", actor_id=actor.user_id, changes={"number": req.number})
    req.delete()


@transaction.atomic
def submit(actor: Actor, request_id, *, expected_version):
    req = _lock(request_id)
    req.assert_editable()
    _require_owner(actor, req, "Отправить заявку")
    _require_status(req, (AccountableStatus.DRAFT,), "отправка")
    check_version(req, expected_version)
    _check_budget(req, lock=True)
    try:
        signoff.start_process(subject_type=REQUEST_SUBJECT, subject_id=str(req.pk),
                              initiator_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise DomainError("E-SGN-01", str(exc), status=409) from exc
    req.refresh_from_db()
    req.version += 1
    req.save(update_fields=["version", "updated_at"])
    audit.record(req, "submitted", actor_id=actor.user_id, changes={"amount": str(req.amount)})
    return req


@transaction.atomic
def mark_paid(actor: Actor, request_id, *, expected_version):
    """Бухгалтер выдал деньги — заявка ждёт авансовых отчётов."""
    req = _lock(request_id)
    if not actor.can("bpp.accountable.payment", "edit"):
        raise _deny("Отметить выдачу подотчётных средств может бухгалтер.")
    _require_status(req, (AccountableStatus.AWAITING_ACCOUNTING,), "отметка выдачи")
    check_version(req, expected_version)
    req.status = AccountableStatus.AWAITING_REPORT
    req.paid_at, req.paid_by = timezone.now(), actor.user_id
    req.version += 1
    req.updated_by = actor.user_id
    req.save(update_fields=["status", "paid_at", "paid_by", "version", "updated_by",
                            "updated_at"])
    audit.record(req, "paid", actor_id=actor.user_id, changes={"amount": str(req.amount)})
    return req


# ── авансовые отчёты ────────────────────────────────────────────────────

def reported_amount(req: AccountableFundsRequest) -> Decimal:
    return (req.reports.filter(approval_state=signoff.ApprovalState.APPROVED)
            .aggregate(total=Sum("amount"))["total"] or ZERO)


def _held_amount(req: AccountableFundsRequest, *, exclude_report_id=None) -> Decimal:
    """Одобренные и отправленные отчёты держат остаток, пока идёт согласование."""
    rows = req.reports.filter(approval_state__in=(signoff.ApprovalState.APPROVED,
                                                  signoff.ApprovalState.PENDING))
    if exclude_report_id is not None:
        rows = rows.exclude(pk=exclude_report_id)
    return rows.aggregate(total=Sum("amount"))["total"] or ZERO


def _check_capacity(req: AccountableFundsRequest, amount: Decimal, *, exclude_report_id=None):
    remaining = req.amount - _held_amount(req, exclude_report_id=exclude_report_id)
    if amount > remaining:
        raise DomainError(
            "E-ACN-01", f"Сумма отчёта превышает остаток подотчётных средств: доступно "
                        f"{fmt(remaining, req.currency)}.",
            fields=[{"field": "amount", "message": "Больше остатка",
                     "available": str(remaining)}])


@transaction.atomic
def add_report(actor: Actor, request_id, *, expense_name: str, amount, upload) -> AdvanceReport:
    req = _lock(request_id)
    _require_owner(actor, req, "Добавлять авансовые отчёты")
    _require_status(req, (AccountableStatus.AWAITING_REPORT,), "авансовый отчёт")
    amount = money(amount)
    if amount <= 0:
        raise DomainError("E-VAL-01", "Сумма отчёта должна быть больше нуля.",
                          fields=[{"field": "amount", "message": "Сумма > 0"}])
    if not (expense_name or "").strip():
        raise DomainError("E-VAL-01", "Укажите наименование затрат.",
                          fields=[{"field": "expense_name", "message": "Не заполнено"}])
    if upload is None:
        raise DomainError("E-VAL-01", "Приложите подтверждающий документ.",
                          fields=[{"field": "file", "message": "Нет файла"}])
    _check_capacity(req, amount)
    report = AdvanceReport.objects.create(
        request=req, expense_name=expense_name.strip()[:500], amount=amount,
        created_by=actor.user_id, updated_by=actor.user_id)
    core_files.attach(report, REPORT_FILE, data=upload.read(), filename=upload.name,
                      mime=upload.content_type or "application/octet-stream",
                      actor_id=actor.user_id, request=actor.request)
    audit.record(req, "report_added", actor_id=actor.user_id,
                 changes={"report": str(report.pk), "amount": str(amount)})
    return report


@transaction.atomic
def submit_report(actor: Actor, report_id) -> AdvanceReport:
    report = AdvanceReport.objects.select_for_update().filter(pk=report_id).first()
    if report is None:
        raise DomainError("E-NOT-FOUND", "Авансовый отчёт не найден.", status=404)
    req = _lock(report.request_id)
    _require_owner(actor, req, "Отправлять авансовые отчёты")
    _require_status(req, (AccountableStatus.AWAITING_REPORT,), "отправка отчёта")
    report.assert_editable()
    _check_capacity(req, report.amount, exclude_report_id=report.pk)
    try:
        signoff.start_process(subject_type=REPORT_SUBJECT, subject_id=str(report.pk),
                              initiator_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise DomainError("E-SGN-01", str(exc), status=409) from exc
    report.refresh_from_db()
    return report


def get_visible_report(actor: Actor, report_id) -> AdvanceReport:
    report = AdvanceReport.objects.filter(pk=report_id).select_related("request").first()
    if report is None or not (can_view(actor, report.request) or signoff.is_participant(
            actor.user_id, REPORT_SUBJECT, str(report.pk))):
        raise DomainError("E-NOT-FOUND", "Авансовый отчёт не найден.", status=404)
    return report


def report_file_link(actor: Actor, report_id) -> dict:
    report = get_visible_report(actor, report_id)
    files = core_files.list_files(report)
    if not files:
        raise DomainError("E-NOT-FOUND", "У отчёта нет файла.", status=404)
    return {"url": core_files.download_url(files[0]["id"], user_id=actor.user_id,
                                           request=actor.request)}


# ── колбэки согласования ────────────────────────────────────────────────

def _to(request_id, status: str) -> None:
    AccountableFundsRequest.objects.filter(pk=request_id).update(status=status)


def on_request_started(request_id) -> None:
    _to(request_id, AccountableStatus.ON_REVIEW)


def on_request_approved(request_id) -> None:
    _to(request_id, AccountableStatus.AWAITING_ACCOUNTING)


def on_request_back_to_draft(request_id) -> None:
    """Отказ, возврат и отзыв — снова черновик, резерв снят (как в contracts)."""
    _to(request_id, AccountableStatus.DRAFT)


def on_report_approved(report_id) -> None:
    """Одобренные отчёты покрыли сумму — заявка закрыта.

    Движок зовёт колбэк ДО записи ``approval_state`` отчёта, поэтому сам
    отчёт считается явно (тот же приём, что в contracts)."""
    report = AdvanceReport.objects.select_for_update().filter(pk=report_id).first()
    if report is None:
        return
    req = AccountableFundsRequest.objects.select_for_update().get(pk=report.request_id)
    reported = reported_amount(req)
    if report.approval_state != signoff.ApprovalState.APPROVED:
        reported += report.amount
    if req.amount - reported <= ZERO:
        req.status = AccountableStatus.CLOSED
        req.save(update_fields=["status", "updated_at"])


# ── чтение ──────────────────────────────────────────────────────────────

def serialize_report(report: AdvanceReport) -> dict:
    return {"id": str(report.id), "expense_name": report.expense_name,
            "amount": report.amount, "approval_state": report.approval_state,
            "created_at": report.created_at, "files": core_files.list_files(report)}


def card(actor: Actor, req: AccountableFundsRequest) -> dict:
    reported = reported_amount(req)
    return {
        "id": str(req.id), "number": req.number, "status": req.status,
        "approval_state": req.approval_state, "version": req.version,
        "project_id": str(req.project_id), "article_id": str(req.article_id),
        "article_name": budget_balance.article_name(req.article_id),
        "amount": req.amount, "currency": req.currency, "goal": req.goal,
        "accountable_user_id": req.accountable_user_id,
        "paid_at": req.paid_at, "paid_by": req.paid_by,
        "reported_amount": reported, "remaining_amount": req.amount - reported,
        "reports": [serialize_report(r) for r in req.reports.all()],
        "current_holders": signoff.current_holders(REQUEST_SUBJECT, [str(req.pk)]).get(
            str(req.pk)),
        "allowed_actions": allowed_actions(actor, req),
        "created_at": req.created_at,
    }


def registry(actor: Actor, *, status: str | None = None) -> list[dict]:
    rows = AccountableFundsRequest.objects.filter(is_migrated=False).order_by("-created_at")
    if not sees_all(actor):
        rows = rows.filter(accountable_user_id=actor.user_id)
    if status:
        rows = rows.filter(status=status)
    return [{"id": str(r.id), "number": r.number, "status": r.status, "amount": r.amount,
             "currency": r.currency, "goal": r.goal, "project_id": str(r.project_id),
             "article_id": str(r.article_id), "accountable_user_id": r.accountable_user_id,
             "created_at": r.created_at} for r in rows[:500]]
