"""Запросы доступа к задаче (решения K-31, K-32; мастер-план канбана §3.5,
§6.2; этап S2).

Кто видит задачу, но не в нужной роли, просит «на исполнение» (стать
основным исполнителем) или «на владение» (стать руководителем). Решающие
зависят от вида: «владение» — руководитель задачи и глава её отдела;
«исполнение» — руководитель, делегаты, автор, исполнители и тот же глава.
Нет никого (кроме самого запросившего) — решает администратор задач, ему же
и уведомление. С полной правкой запрос не нужен: назначить себя можно самому. Набор
считается на момент решения: снятый с задачи, пока запрос ждал, решить его
уже не может. Решение и смена ролей — одной транзакцией под блокировкой
запроса и задачи: второй решающий получает 409 с тем, кто и как решил.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.companies import interface as companies
from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from apps.users import interface as users
from htqweb.errors import DomainError
from htqweb.fallback import fallback
from htqweb.tenancy.context import current_company_or_none

from ..models import (AccessApproveMode, AccessRequestKind, AccessRequestStatus, AssigneeRole,
                      Task, TaskAccessRequest, TaskActivity, TaskAssignee, TaskDelegate)
from . import hydration
from . import task_notify
from . import task_scope
from . import task_service

INBOX_LIMIT = 500
MINE_DAYS = 90
TASK_DECIDED_LIMIT = 20
HISTORY_LIMIT = 50


# ── кто решает ──────────────────────────────────────────────────────────

def head_ids(task: Task) -> set[int]:
    """Главы отдела задачи: держатели ``Department.manager`` её основного
    отдела и отделов-предков (поддерево главы содержит отдел задачи)."""
    if not task.department_id:
        return set()
    try:
        departments = [task.department_id] + [row["id"] for row
                                              in hr.org_ancestors(task.department_id)]
        return set(hr.department_manager_user_ids(departments).values())
    except ServiceDisabled as exc:
        return fallback("tasks.access_requests.heads_unavailable", set(),
                        reason="hr выключен — глава отдела задачи не найден",
                        expected=True, exc=exc)


def deciders(task: Task, kind: str) -> set[int]:
    """Решающие запроса этого вида (K-31) — без учёта запросившего."""
    people = {task.supervisor_id}
    if kind == AccessRequestKind.EXECUTE:
        people |= {task.reporter_id, task.assignee_id}
        people |= set(TaskDelegate.objects.filter(task=task).values_list("user_id", flat=True))
        people |= set(TaskAssignee.objects.filter(task=task).values_list("user_id", flat=True))
    people |= head_ids(task)
    people.discard(None)
    return people


def fallback_deciders() -> set[int]:
    """Кому решать, когда по K-31 некому: администраторы задач
    (``is_elevated`` — флаги учётки) из действующих участников компании.
    Нужны для уведомлений: решать им позволяет ``scope.elevated``, а узнать о
    запросе — только отсюда."""
    people = set(users.elevated_user_ids())
    slug = current_company_or_none()
    if slug:
        people &= set(companies.active_member_ids(slug))
    return people


def may_decide(task: Task, kind: str, requester_id: int, scope) -> bool:
    people = deciders(task, kind) - {requester_id}
    if people:
        return scope.user_id in people
    return scope.elevated


def in_role(task: Task, kind: str, user_id: int) -> bool:
    """Уже в той роли, которую просит: основной исполнитель / руководитель."""
    if kind == AccessRequestKind.EXECUTE:
        return task.assignee_id == user_id
    return task.supervisor_id == user_id


def can_request(task: Task, scope) -> list[str]:
    """Какие запросы вызывающий может отправить сейчас (кнопки карточки).

    С полной правкой запрашивать нечего: исполнителя и руководителя такой
    человек назначает сам (`PATCH assignees`, `PATCH supervisor`).
    """
    if task_service.can_edit(task, scope):
        return []
    pending = set(TaskAccessRequest.objects.filter(
        task=task, requester_id=scope.user_id, status=AccessRequestStatus.PENDING)
        .values_list("kind", flat=True))
    return [kind for kind in (AccessRequestKind.EXECUTE, AccessRequestKind.OWN)
            if not in_role(task, kind, scope.user_id) and kind not in pending]


def pending_to_decide(task: Task, scope) -> int:
    """Сколько ждущих запросов к задаче может решить вызывающий."""
    return sum(1 for row in TaskAccessRequest.objects.filter(
        task=task, status=AccessRequestStatus.PENDING)
        if may_decide(task, row.kind, row.requester_id, scope))


# ── ответ ───────────────────────────────────────────────────────────────

def _person(users: dict, user_id: int | None) -> dict | None:
    return {"id": user_id, "name": hydration.user_name(users, user_id)} if user_id else None


def _payload(row: TaskAccessRequest, users: dict) -> dict:
    task = row.task
    return {
        "id": row.pk,
        "task": {"id": task.pk, "key": task.key, "summary": task.summary},
        "requester": _person(users, row.requester_id),
        "kind": row.kind,
        "comment": row.comment,
        "status": row.status,
        "approve_mode": row.approve_mode,
        "replaced": _person(users, row.replaced_user_id),
        "decided_by": _person(users, row.decided_by_id),
        "decided_at": row.decided_at,
        "decision_comment": row.decision_comment,
        "created_at": row.created_at,
    }


def _payloads(rows: list[TaskAccessRequest]) -> list[dict]:
    users = hydration.user_briefs(uid for row in rows
                                  for uid in (row.requester_id, row.replaced_user_id,
                                              row.decided_by_id))
    return [_payload(row, users) for row in rows]


# ── запрос ──────────────────────────────────────────────────────────────

def _log(task: Task, actor_id: int, field: str, row: TaskAccessRequest) -> None:
    task_service._log(task, actor_id, field, None, f"{row.kind}:{row.requester_id}")


@transaction.atomic
def request_access(task_id: int, request, *, kind: str, comment: str = "") -> dict:
    task_service.load_for_action(task_id, request)                   # невидимая — 404
    scope = task_scope.for_request(request)
    task = Task.objects.select_for_update().get(pk=task_id)
    if in_role(task, kind, scope.user_id):
        raise DomainError("task_access_already", "Вы уже в этой роли", status=409)
    if task_service.can_edit(task, scope):
        raise DomainError("task_access_unneeded",
                          "Запрос не нужен: вы можете назначить себя сами", status=409)
    try:
        with transaction.atomic():
            row = TaskAccessRequest.objects.create(task=task, requester_id=scope.user_id,
                                                   kind=kind, comment=comment)
    except IntegrityError as exc:
        raise DomainError("task_access_pending", "Такой запрос уже ждёт решения",
                          status=409) from exc
    _log(task, scope.user_id, "access_requested", row)
    people = deciders(task, kind) - {scope.user_id}
    task_notify.access_requested(task, scope.user_id, kind,
                                 people or (fallback_deciders() - {scope.user_id}))
    return _payloads([row])[0]


def _decided_conflict(row: TaskAccessRequest) -> DomainError:
    users = hydration.user_briefs([row.decided_by_id])
    return DomainError("task_access_decided", "Запрос уже решён", status=409, details={
        "status": row.status, "approve_mode": row.approve_mode,
        "decided_by": ({"id": row.decided_by_id,
                        "name": hydration.user_name(users, row.decided_by_id)}
                       if row.decided_by_id else None),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    })


def _lock(request_id: int, request) -> tuple[TaskAccessRequest, Task]:
    """Запрос и задача под блокировкой; невидимая задача — 404."""
    row = TaskAccessRequest.objects.filter(pk=request_id).first()
    if row is None:
        raise Http404("Access request not found")
    task_service.load_for_action(row.task_id, request)
    task = Task.objects.select_for_update().get(pk=row.task_id)
    row = TaskAccessRequest.objects.select_for_update().get(pk=request_id)
    return row, task


def _make_owner(task: Task, row: TaskAccessRequest, mode: str, actor_id: int) -> int | None:
    requester = row.requester_id
    if mode == AccessApproveMode.DELEGATE:
        if not TaskDelegate.objects.filter(task=task, user_id=requester).exists():
            TaskDelegate.objects.create(task=task, user_id=requester, granted_by_id=actor_id)
            task_service._log(task, actor_id, "delegates", None, f"+{requester}")
        return None
    replaced = task.supervisor_id
    task_service._log(task, actor_id, "supervisor_id", replaced, requester)
    task.supervisor_id = requester
    task.save(update_fields=["supervisor_id", "updated_at"])
    # Руководитель — больше не делегат: полная правка у него и так есть.
    if TaskDelegate.objects.filter(task=task, user_id=requester).delete()[0]:
        task_service._log(task, actor_id, "delegates", requester, None)
    return replaced if replaced != requester else None


def _make_executor(task: Task, row: TaskAccessRequest, actor_id: int) -> int | None:
    requester = row.requester_id
    replaced = task.assignee_id
    if replaced is not None and replaced != requester:
        TaskAssignee.objects.filter(task=task, user_id=replaced).delete()
    own = TaskAssignee.objects.filter(task=task, user_id=requester).first()
    if own is None:
        TaskAssignee.objects.create(task=task, user_id=requester, role=AssigneeRole.PRIMARY,
                                    seen_at=timezone.now())
    else:
        own.role = AssigneeRole.PRIMARY
        own.save(update_fields=["role"])
    task_service._log(task, actor_id, "assignee_id", replaced, requester)
    task.assignee_id = requester
    task.save(update_fields=["assignee_id", "updated_at"])
    return replaced if replaced != requester else None


@transaction.atomic
def decide(request_id: int, request, *, approve: bool, mode: str | None = None,
           comment: str = "") -> dict:
    row, task = _lock(request_id, request)
    scope = task_scope.for_request(request)
    if row.status != AccessRequestStatus.PENDING:
        raise _decided_conflict(row)
    people = deciders(task, row.kind) - {row.requester_id}
    allowed = scope.user_id in people if people else scope.elevated
    if not allowed:
        raise DomainError("task_access_forbidden", "Решить этот запрос вы не можете",
                          status=403)
    replaced = None
    if approve:
        if row.kind == AccessRequestKind.OWN:
            if mode not in (AccessApproveMode.REPLACE, AccessApproveMode.DELEGATE):
                raise DomainError("task_access_mode",
                                  "Выберите: передать владение или сделать делегатом",
                                  status=422)
            replaced = _make_owner(task, row, mode, scope.user_id)
        else:
            if mode not in (None, AccessApproveMode.REPLACE):
                raise DomainError("task_access_mode",
                                  "Запрос на исполнение одобряется только заменой",
                                  status=422)
            mode = AccessApproveMode.REPLACE
            replaced = _make_executor(task, row, scope.user_id)
    row.status = AccessRequestStatus.APPROVED if approve else AccessRequestStatus.REJECTED
    row.approve_mode = mode if approve else None
    row.replaced_user_id = replaced
    row.decided_by_id = scope.user_id
    row.decided_at = timezone.now()
    row.decision_comment = comment
    row.save()
    _log(task, scope.user_id, "access_approved" if approve else "access_rejected", row)
    task_notify.access_decided(task, scope.user_id, row, approved=approve,
                               other_deciders=(people or fallback_deciders()) - {scope.user_id},
                               replaced_user_id=replaced)
    return _payloads([row])[0]


@transaction.atomic
def cancel(request_id: int, request) -> None:
    row, task = _lock(request_id, request)
    scope = task_scope.for_request(request)
    if row.requester_id != scope.user_id:
        raise PermissionDenied("Отозвать запрос может только тот, кто его отправил")
    if row.status != AccessRequestStatus.PENDING:
        raise _decided_conflict(row)
    row.status = AccessRequestStatus.CANCELLED
    row.save(update_fields=["status", "updated_at"])
    _log(task, scope.user_id, "access_cancelled", row)


# ── списки ──────────────────────────────────────────────────────────────

def for_task(task_id: int, request) -> list[dict]:
    """Решающим — все ждущие и последние решённые; остальным — только свои."""
    task = task_service.load_for_action(task_id, request)
    scope = task_scope.for_request(request)
    rows = TaskAccessRequest.objects.filter(task=task).select_related("task")
    decider = any(may_decide(task, kind, 0, scope) for kind in AccessRequestKind.values)
    if not decider:
        rows = rows.filter(requester_id=scope.user_id)
    pending = list(rows.filter(status=AccessRequestStatus.PENDING).order_by("created_at"))
    decided = list(rows.exclude(status=AccessRequestStatus.PENDING)
                   .order_by("-decided_at", "-pk")[:TASK_DECIDED_LIMIT])
    return _payloads(pending + decided)


def inbox(request) -> dict:
    """Панель «Запросы» (K-32): ждут моего решения и мои запросы за 90 дней."""
    scope = task_scope.for_request(request)
    visible = task_service.visibility_q(scope)
    pending = TaskAccessRequest.objects.filter(status=AccessRequestStatus.PENDING,
                                               task__is_deleted=False)
    if visible is not None:
        pending = pending.filter(task__in=Task.objects.filter(visible).values("pk"))
    to_decide = [row for row in pending.select_related("task").order_by("created_at")[:INBOX_LIMIT]
                 if row.requester_id != scope.user_id
                 and may_decide(row.task, row.kind, row.requester_id, scope)]
    since = timezone.now() - timedelta(days=MINE_DAYS)
    mine = list(TaskAccessRequest.objects.filter(requester_id=scope.user_id, created_at__gte=since)
                .select_related("task").order_by("-created_at"))
    return {"to_decide": _payloads(to_decide), "mine": _payloads(mine),
            "to_decide_count": len(to_decide)}


def _parse_date(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError as exc:
        raise DomainError("history_filter_invalid", "Дата — в виде ГГГГ-ММ-ДД",
                          status=422) from exc


def department_history(department_id: int, request, params) -> dict:
    """История отдела (K-32): запросы доступа и передачи владения (смена
    руководителя задачи — решением по запросу или вручную) по задачам
    поддерева отдела, одной лентой по времени. Право — глава этого отдела,
    держатель «досок всех отделов», администратор задач; иначе 404."""
    scope = task_scope.for_request(request)
    if not (scope.elevated or scope.all_departments or department_id in scope.managed_subtree):
        raise Http404("Board not found")
    subtree = hr.department_subtree_ids([department_id]).get(department_id) or [department_id]
    tasks = Task.objects.filter(is_deleted=False).filter(task_service.department_q(subtree))
    kind = (params.get("kind") or "").strip() or None
    status = (params.get("status") or "").strip() or None
    start, end = _parse_date(params.get("from")), _parse_date(params.get("to"))
    if kind not in (None, "execute", "own", "transfer"):
        raise DomainError("history_filter_invalid", "Неизвестный вид", status=422)

    entries = []
    if kind != "transfer":
        rows = TaskAccessRequest.objects.filter(task__in=tasks.values("pk")).select_related("task")
        if kind:
            rows = rows.filter(kind=kind)
        if status:
            rows = rows.filter(status=status)
        if start:
            rows = rows.filter(created_at__date__gte=start)
        if end:
            rows = rows.filter(created_at__date__lte=end)
        entries += [("request", row.created_at, row) for row
                    in rows.order_by("-created_at")[:HISTORY_LIMIT]]
    if kind in (None, "transfer") and not status:
        moves = TaskActivity.objects.filter(task__in=tasks.values("pk"),
                                            field_name="supervisor_id").select_related("task")
        if start:
            moves = moves.filter(created_at__date__gte=start)
        if end:
            moves = moves.filter(created_at__date__lte=end)
        entries += [("transfer", row.created_at, row) for row
                    in moves.order_by("-created_at")[:HISTORY_LIMIT]]
    entries.sort(key=lambda entry: entry[1], reverse=True)
    entries = entries[:HISTORY_LIMIT]

    requests = [row for kind_, _at, row in entries if kind_ == "request"]
    request_payloads = {row.pk: payload for row, payload in zip(requests, _payloads(requests))}
    move_users = hydration.user_briefs(
        uid for kind_, _at, row in entries if kind_ == "transfer"
        for uid in (row.actor_id, _int(row.old_value), _int(row.new_value)))
    items = []
    for kind_, at, row in entries:
        if kind_ == "request":
            items.append({"type": "request", "at": at, "request": request_payloads[row.pk]})
        else:
            items.append({
                "type": "transfer", "at": at,
                "task": {"id": row.task.pk, "key": row.task.key, "summary": row.task.summary},
                "by": _person(move_users, row.actor_id),
                "from": _person(move_users, _int(row.old_value)),
                "to": _person(move_users, _int(row.new_value)),
            })
    return {"items": items}


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None

