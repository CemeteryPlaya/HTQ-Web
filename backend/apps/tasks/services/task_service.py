"""Core task business logic.

Ported from ``services/task/app/services/task_service.py`` plus the query
side of ``app/repositories/task_repo.py``. The FastAPI split (service +
repository) collapses here: the ORM is the repository, so keeping a separate
one would be a layer of pass-throughs. Filtering/visibility helpers that
lived in ``TaskRepository`` are the ``_*_q`` builders below.

Jira + SharePoint workflow, unchanged from the original:

* ``Task.assignee_id`` is the *primary* assignee; the source of truth for
  the full crew is ``TaskAssignee``, which carries a role. The two are kept
  in sync here, never by callers.
* ``Task.supervisor_id`` is single; the supervisor grants edit rights to
  delegates.
* Watchers follow a task — visible, notified, no edit rights.
* ``progress_percent`` is independent of status; reaching ``done`` fills it
  to 100 (in ``Task.apply_transition``).
"""

from __future__ import annotations

import copy
import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied

from htqweb import date_rules
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncDate
from django.http import Http404

from htqweb.errors import DomainError
from django.utils import timezone

from ..models import (
    AssigneeRole,
    BoardKind,
    DepartmentLinkKind,
    Label,
    Status,
    TERMINAL_STATUSES,
    TRANSITIONS,
    Task,
    TaskActivity,
    TaskAssignee,
    TaskDelegate,
    TaskDepartmentLink,
    TaskWatcher,
)
from . import board_scope
from . import department_rules
from . import hydration
from . import roadmap_service
from . import site_service
from . import task_notify
from . import task_scope
from .automation import context as automation_context
from .automation import events as automation
from .automation.context import Event
from .reference_service import resolve_task_type_id
from .sequence_service import due_date_from_working_days, next_task_key

logger = logging.getLogger(__name__)

# Scalar fields whose changes are written to the activity log. Copied from
# the original's ``TRACKED_FIELDS`` — the list is a product decision (what
# the task history shows), not an implementation detail.
TRACKED_FIELDS = [
    "summary", "description", "task_type_id", "priority", "status",
    "assignee_id", "supervisor_id", "department_id", "project_id", "roadmap_id",
    "site_id",
    "site_block_id",
    "contractor_id", "contractor_worker_id", "progress_percent",
    "due_date", "start_date", "estimated_working_days",
]


# ─────────────────────────────────────────────────────────────────────────
# Visibility
# ─────────────────────────────────────────────────────────────────────────

def user_department_id(user_id: int) -> int | None:
    """The caller's HR department.

    The original read it from the local user replica; with the replica gone
    (Р2) it comes from ``apps.hr.interface`` — see
    ``hydration.employee_department_id`` for what ``None`` means.
    """
    return hydration.employee_department_id(user_id)


def participant_q(user_id: int) -> Q:
    """Tasks where the user has any stake at all."""
    return (
        Q(assignee_id=user_id)
        | Q(reporter_id=user_id)
        | Q(supervisor_id=user_id)
        | Q(assignees__user_id=user_id)
        | Q(delegates__user_id=user_id)
        | Q(watchers__user_id=user_id)
    )


def soft_edit_q(user_id: int) -> Q:
    """Задачи, о ходе которых пользователь вправе отчитаться.

    Условие-двойник ``can_progress``: то же самое правило, но выраженное
    запросом, чтобы список можно было получить одной выборкой, а не
    проверять права построчно в Python.

    Наблюдателей здесь НЕТ, в отличие от ``participant_q``: следить за
    задачей и заявлять о выполненном объёме — разные вещи. Разъедется с
    ``can_progress`` — и экран покажет строки, сохранение которых даст 403.
    """
    return (
        Q(assignee_id=user_id)
        | Q(reporter_id=user_id)
        | Q(supervisor_id=user_id)
        | Q(assignees__user_id=user_id)
        | Q(delegates__user_id=user_id)
    )


def department_q(department_ids, *, member_only: bool = False) -> Q:
    """Задачи этих отделов: основной отдел или связь с отделом.

    ``Exists``, а не джойн: ``participant_q`` уже множит строки джойнами
    (``filtered_tasks`` их схлопывает ``distinct``), ещё один к связям отделов
    множил бы их дальше. ``member_only`` — без отделов-отправителей (``origin``
    видит задачу, но не «берёт в работу» и не правит её, S1-03).
    """
    ids = list(department_ids)
    links = TaskDepartmentLink.objects.filter(task=OuterRef("pk"), department_id__in=ids)
    if member_only:
        links = links.filter(kind=DepartmentLinkKind.MEMBER)
    return Q(department_id__in=ids) | Exists(links)


def visibility_q(scope) -> Q | None:
    """Что видит вызывающий (мастер-план канбан-досок §5.2).

    ``None`` — без ограничений (``elevated`` и внутренние вызовы без
    ``scope``). Иначе: участие в задаче | поддеревья своего и управляемых
    отделов (основной отдел или связь) | все отделы (узел
    ``tasks.departments.all``) | задачи досок «Проектов» держателя
    ``project.board``. Задача без проекта, отдела и связей сюда попадает только
    через участие (K-10).
    """
    if scope is None or scope.elevated:
        return None
    q = participant_q(scope.user_id)
    if scope.department_ids:
        q |= department_q(scope.department_ids)
    if scope.all_departments:
        q |= (Q(department_id__isnull=False)
              | Exists(TaskDepartmentLink.objects.filter(task=OuterRef("pk"))))
    boards = board_scope.board_q(scope.board_refs, prefix="project__")
    if boards is not None:
        q |= boards
    return q


def _report_visibility_q(user_id: int, department_id: int | None) -> Q:
    q = Q(Q(assignee_id=user_id) | Q(assignees__user_id=user_id),
          status__in=list(TERMINAL_STATUSES))
    if department_id is not None:
        q |= Q(department_id=department_id, assignee_id__isnull=True,
               status__in=[Status.BACKLOG, Status.TODO])
    return q


def report_visibility_q(token) -> Q | None:
    """Прежнее правило статистики ``/tasks/stats`` — не меняется вместе с
    досками (спека этапа 1, S1-11): свои завершённые плюс неразобранные
    своего отдела. ``None`` — без ограничений."""
    if token.is_elevated:
        return None
    if token.user_id is None:
        return Q(pk__in=[])
    return _report_visibility_q(token.user_id, user_department_id(token.user_id))


# ─────────────────────────────────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────────────────────────────────

def _base_queryset():
    return Task.objects.filter(is_deleted=False)


def filtered_tasks(*, status=None, priority=None, task_type=None,
                   task_type_id=None, assignee_id=None, reporter_id=None,
                   supervisor_id=None, department_id=None, project_id=None,
                   project_unset=False, roadmap_id=None, roadmap_unset=False,
                   site_id=None, site_unset=False, site_block_id=None,
                   contractor_id=None, contractor_unset=False,
                   parent_id=None, label_id=None,
                   search=None, scope=None, legacy_q=None, extra_q=None):
    """``scope`` — ``TaskScope`` вызывающего (``None`` — без ограничений);
    ``legacy_q`` — готовое условие прежнего правила, только для
    ``task_stats`` (S1-11); ``extra_q`` — сужение поверх видимости (вкладки
    ``scope=mine|department`` списка, канбан K1.6)."""
    qs = _base_queryset()

    vq = legacy_q if legacy_q is not None else visibility_q(scope)
    if vq is not None:
        qs = qs.filter(vq)
    if extra_q is not None:
        qs = qs.filter(extra_q)

    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if task_type:
        qs = qs.filter(task_type__slug=task_type)
    if task_type_id is not None:
        qs = qs.filter(task_type_id=task_type_id)
    if assignee_id is not None:
        # Either the denormalised primary FK or the crew table, so
        # "tasks X works on" is right whether X is primary or collaborator.
        qs = qs.filter(Q(assignee_id=assignee_id)
                       | Q(assignees__user_id=assignee_id))
    if reporter_id is not None:
        qs = qs.filter(reporter_id=reporter_id)
    if supervisor_id is not None:
        qs = qs.filter(supervisor_id=supervisor_id)
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if project_unset:
        qs = qs.filter(project_id__isnull=True)
    if roadmap_id is not None:
        qs = qs.filter(roadmap_id=roadmap_id)
    if roadmap_unset:
        # Задачи проекта вне пакетов работ — отдельная корзина, а не ошибка:
        # так живут все задачи, заведённые до появления роудмапов.
        qs = qs.filter(roadmap_id__isnull=True)
    if site_id is not None:
        qs = qs.filter(site_id=site_id)
    if site_unset:
        # Historical tasks carry no object and never will (there is nothing
        # to derive one from), so "no object" is a first-class bucket the
        # reports need to be able to isolate — not an error state.
        qs = qs.filter(site_id__isnull=True)
    if site_block_id is not None:
        qs = qs.filter(site_block_id=site_block_id)
    if contractor_id is not None:
        qs = qs.filter(contractor_id=contractor_id)
    if contractor_unset:
        # «Своя команда» — задачи без партнёра. Отдельный флаг, а не
        # contractor_id=0: NULL нельзя выразить через параметр-число.
        qs = qs.filter(contractor_id__isnull=True)
    if parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    if label_id is not None:
        qs = qs.filter(labels__id=label_id)
    if search:
        qs = qs.filter(Q(summary__icontains=search)
                       | Q(description__icontains=search)
                       | Q(key__icontains=search))

    # The visibility and assignee filters join across to-many tables
    # (assignees/delegates/watchers/labels), which multiplies rows. Without
    # distinct() a task the user reaches through two roles would appear
    # twice in the list — the original avoided it with EXISTS subqueries.
    return qs.distinct()


def list_tasks(*, offset: int = 0, limit: int = 50, **filters) -> list[Task]:
    qs = (filtered_tasks(**filters)
          .select_related("task_type", "project", "roadmap", "site",
                          "site_block", "parent", "contractor",
                          "contractor_worker")
          .prefetch_related("labels", "assignees", "department_links",
                            "subtasks")
          .order_by("-created_at"))
    return list(qs[offset:offset + limit])


def get_task(task_id: int, *, scope=None) -> Task:
    """Load one task honouring visibility. Raises 404 when out of scope —
    deliberately indistinguishable from "does not exist", so the endpoint
    does not leak the existence of tasks the caller may not see.
    ``scope=None`` — без ограничений (внутренние вызовы после проверки)."""
    qs = filtered_tasks(scope=scope)
    task = (qs.select_related("task_type", "project", "roadmap", "site",
                              "site_block", "parent", "contractor",
                              "contractor_worker")
            # Both ends of both link directions: the response reports
            # source/target absolutely, so an outgoing link still needs its
            # source (this task) resolved as an object.
            .prefetch_related("labels", "assignees", "delegates", "watchers",
                              "comments", "attachments", "activities",
                              # ``__volume_type``: карточка печатает название
                              # вида работ и единицу, без джойна это запрос
                              # на каждую строку объёма.
                              "volumes__volume_type",
                              "outgoing_links__source", "outgoing_links__target",
                              "incoming_links__source", "incoming_links__target",
                              "department_links", "subtasks")
            .filter(pk=task_id).first())
    if task is None:
        raise Http404("Task not found")
    return task


def load_for_action(task_id: int, request) -> Task:
    """Visibility-checked load used by every mutating endpoint.

    Does NOT check write permission — the caller decides whether full edit,
    soft edit, or mere visibility is required.

    Takes the REQUEST, not the token (канбан K1.3, спека этапа 1 S1-01): the
    caller's ``TaskScope`` is computed once per request and cached on it.
    """
    return get_task(task_id, scope=task_scope.for_request(request))


# ─────────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────────

def is_head_of(task: Task, scope) -> bool:
    """Глава отдела задачи (K-06): основной отдел задачи или её связь
    «участник» — в поддереве отдела, которым руководит вызывающий. Связь
    «отправитель» прав не даёт (S1-03). ``department_links`` — из prefetch
    ``get_task``."""
    if scope is None or not scope.managed_subtree:
        return False
    if task.department_id in scope.managed_subtree:
        return True
    return any(link.kind == DepartmentLinkKind.MEMBER
               and link.department_id in scope.managed_subtree
               for link in task.department_links.all())


def can_edit(task: Task, scope) -> bool:
    """Full edit — any field. Elevated / reporter / supervisor / delegate /
    глава отдела задачи (K-06: для правки он равен руководителю)."""
    if scope.elevated:
        return True
    if task.reporter_id == scope.user_id or task.supervisor_id == scope.user_id:
        return True
    if is_head_of(task, scope):
        return True
    return task.delegates.filter(user_id=scope.user_id).exists()


def tab_q(tab: str | None, scope) -> Q | None:
    """Вкладки списка ``scope=mine|department`` (канбан K1.6, S1-04): «мои» —
    участие (то, что станет личной доской, K-03), «отдел» — поддеревья своего
    отдела и управляемых, без «всех отделов» и досок проектов."""
    if tab == "mine":
        return participant_q(scope.user_id)
    if tab == "department":
        if scope.elevated:
            return None                                  # администратор видит всё (K-17)
        return department_q(scope.department_ids) if scope.department_ids else Q(pk__in=[])
    return None


def in_own_department(task: Task, scope) -> bool:
    """Задача своего отдела вызывающего: основной отдел или связь-участник в
    поддеревьях его отдела и управляемых. Связь-отправитель, «все отделы» и
    доска проекта сюда не входят (S1-07). ``department_links`` — из prefetch,
    если он есть."""
    if scope is None or not scope.department_ids:
        return False
    if task.department_id in scope.department_ids:
        return True
    return any(link.kind == DepartmentLinkKind.MEMBER
               and link.department_id in scope.department_ids
               for link in task.department_links.all())


def can_claim(task: Task, scope) -> bool:
    """«Взять в работу»: задача своего отдела, без исполнителя, в «Бэклог» или
    «К выполнению» (канбан K1.6). ``assignees`` — из prefetch списка/карточки."""
    return (in_own_department(task, scope)
            and task.assignee_id is None
            and not task.assignees.all()
            and task.status in (Status.BACKLOG, Status.TODO))


@transaction.atomic
def claim(task_id: int, request) -> Task:
    """Взять неразобранную задачу своего отдела в работу (канбан K1.6).

    Видимость — ``load_for_action`` (404); блокировка — ОТДЕЛЬНЫМ запросом:
    выборка видимости с ``distinct`` не совместима с ``FOR UPDATE``. Под
    блокировкой второй одновременный «Взять» видит исполнителя и получает 409.
    """
    scope = task_scope.for_request(request)
    load_for_action(task_id, request)
    task = (Task.objects.select_for_update().prefetch_related("department_links")
            .get(pk=task_id, is_deleted=False))
    if not in_own_department(task, scope):
        raise DomainError("task_claim_forbidden",
                          "Взять в работу можно только задачу своего отдела", status=403)
    if (task.assignee_id is not None or task.assignees.exists()
            or task.status not in (Status.BACKLOG, Status.TODO)):
        raise DomainError("task_claim_unavailable",
                          "Задачу уже взяли в работу", status=409)
    user_id = scope.user_id
    # «Взять в работу» — шаг процесса, как кнопка: запреты доски держат только
    # ручной перенос между колонками (решение L-02, спецификация логики §5).
    TaskAssignee.objects.create(task=task, user_id=user_id, role=AssigneeRole.PRIMARY,
                                seen_at=timezone.now())
    old_status = task.status
    task.assignee_id = user_id
    task.apply_transition(Status.IN_PROGRESS)
    task.save()
    _log(task, user_id, "claim", None, user_id)
    _log(task, user_id, "assignee_id", None, user_id)
    _log(task, user_id, "status", old_status, task.status)
    task_notify.claimed(task, user_id)
    automation.emit(Event("assignee_added", task.pk, user_id, {"user_id": user_id}),
                    Event("moved", task.pk, user_id, {"from": old_status, "to": task.status}))
    return task


def can_progress(task: Task, scope) -> bool:
    """Soft edit — status / progress / comments. Adds any assignee."""
    if can_edit(task, scope):
        return True
    if task.assignee_id == scope.user_id:
        return True
    return task.assignees.filter(user_id=scope.user_id).exists()


def require_full_edit(task: Task, request) -> None:
    if not can_edit(task, task_scope.for_request(request)):
        raise PermissionDenied(
            "Only supervisor, delegate, reporter or admin can edit this task"
        )


def require_soft_edit(task: Task, request) -> None:
    if not can_progress(task, task_scope.for_request(request)):
        raise PermissionDenied(
            "Only assignees, supervisor, delegate, reporter or admin can "
            "change status/progress"
        )


# ─────────────────────────────────────────────────────────────────────────
# Mutations
# ─────────────────────────────────────────────────────────────────────────

def _compose_initial_crew(primary_id: int | None,
                          explicit: list) -> list[tuple[int, str]]:
    """Merge the legacy single ``assignee_id`` with the explicit crew list.

    Rules kept from the original: an explicit primary beats the legacy one,
    and the legacy id counts as primary only when it has no explicit row of
    its own. Returns ``(user_id, role)`` pairs.
    """
    by_user: dict[int, str] = {a.user_id: a.role for a in explicit}
    if primary_id is not None and primary_id not in by_user:
        by_user[primary_id] = AssigneeRole.PRIMARY

    primaries = [uid for uid, role in by_user.items()
                 if role == AssigneeRole.PRIMARY]
    if len(primaries) > 1:
        explicit_primary = {a.user_id for a in explicit
                            if a.role == AssigneeRole.PRIMARY}
        for uid in list(by_user):
            if by_user[uid] == AssigneeRole.PRIMARY and uid not in explicit_primary:
                by_user[uid] = AssigneeRole.COLLABORATOR
    return list(by_user.items())


def _log(task: Task, actor_id: int | None, field_name: str,
         old_value, new_value) -> None:
    TaskActivity.objects.create(
        task=task, actor_id=actor_id, field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        # Правку сделала автоматизация доски — лента подпишет «через
        # автоматизацию» (этап S4).
        via_rule_id=automation_context.current_rule_id(),
    )


def _crew_ids(task: Task) -> set[int]:
    ids = set(TaskAssignee.objects.filter(task=task).values_list("user_id", flat=True))
    if task.assignee_id:
        ids.add(task.assignee_id)
    return ids


def _crew_events(task: Task, actor_id: int | None, before: set[int], after: set[int]) -> list:
    """События автоматизации о смене исполнителей (этап S4)."""
    return ([Event("assignee_added", task.pk, actor_id, {"user_id": uid})
             for uid in sorted(after - before)]
            + [Event("assignee_removed", task.pk, actor_id, {"user_id": uid})
               for uid in sorted(before - after)])


def arrived_events(task: Task, actor_id: int | None, before_keys) -> list:
    """«Пришла на доску» — для домашних досок, которых у задачи не было
    (перевод, смена отдела или проекта; спецификация логики §3): видят только
    правила этой доски."""
    from .board_fields import home_board_keys

    return [Event("card_arrived", task.pk, actor_id,
                  {"board_kind": kind, "board_id": board_id, "status": task.status})
            for kind, board_id in home_board_keys(task) if (kind, board_id) not in before_keys]


def _due_event(task: Task, actor_id: int | None, old, new):
    if old == new:
        return None
    kind = "due_set" if old is None else "due_removed" if new is None else "due_changed"
    return Event(kind, task.pk, actor_id, {"old": str(old) if old else None,
                                           "new": str(new) if new else None})


@transaction.atomic
def create_task(data, user_id: int | None = None, *, scope=None) -> Task:
    """``scope`` — ``TaskScope`` вызывающего: правила отдела, автора,
    начального статуса и родителя (канбан K1.5). ``None`` — внутренний вызов
    без проверок."""
    due_date = data.due_date
    if data.estimated_working_days and data.start_date:
        # A computed deadline wins over a client-sent one, as in the original.
        computed = due_date_from_working_days(data.start_date,
                                              data.estimated_working_days)
        if computed is not None:
            due_date = computed

    crew = _compose_initial_crew(data.assignee_id, data.assignees)
    primary_id = next((uid for uid, role in crew
                       if role == AssigneeRole.PRIMARY), None)

    dept_ids = list(dict.fromkeys(
        ([data.department_id] if data.department_id else [])
        + list(data.department_ids)
    ))
    primary_dept = data.department_id or (dept_ids[0] if dept_ids else None)

    origin = None
    reporter_id = data.reporter_id or user_id
    if scope is not None:
        origin = department_rules.origin_for_create(scope, dept_ids)
        if origin is not None and crew:
            # У получателя задача появляется без исполнителя (K-08): назначить
            # людей чужого отдела отправитель не вправе.
            raise DomainError("task_transfer_assignees",
                              "Задачу в чужой отдел ставят без исполнителя", status=422)
        if not scope.elevated:
            # Автор с клиента — только у администратора (K-25), иначе задачу
            # можно положить на чужую личную доску под чужим именем.
            reporter_id = user_id
            if data.status not in (Status.BACKLOG, Status.TODO):
                raise DomainError("task_status_initial",
                                  "Новая задача начинается с «Бэклог» или «К выполнению»",
                                  status=422)
        if data.parent_id is not None:
            get_task(data.parent_id, scope=scope)        # невидимый родитель — 404 (S1-18)

    # Роудмап первым: он знает проект, площадку и блок, поэтому задаёт их, а
    # не проверяется против них (см. roadmap_service.resolve_task_roadmap).
    project_id, site_id, site_block_id, roadmap_id = (
        roadmap_service.resolve_task_roadmap(
            data.project_id, data.site_id, data.site_block_id, data.roadmap_id))
    # Раскрывается в ValueError -> 400, если объект не относится к проекту;
    # заодно наследует единственный объект проекта, когда он не прислан.
    site_id = site_service.resolve_task_site(project_id, site_id)
    # Блок — после объекта и по уже вычисленному значению (см. update_task).
    site_block_id = site_service.resolve_task_block(site_id, site_block_id)
    if site_block_id and site_id is None:
        site_id = site_service.block_site_id(site_block_id)

    task = Task.objects.create(
        key=next_task_key(),
        summary=data.summary,
        description=data.description,
        task_type_id=resolve_task_type_id(data.task_type_id, data.task_type),
        priority=data.priority,
        status=data.status,
        reporter_id=reporter_id,
        assignee_id=primary_id,
        supervisor_id=data.supervisor_id,
        department_id=primary_dept,
        project_id=project_id,
        roadmap_id=roadmap_id,
        site_id=site_id,
        site_block_id=site_block_id,
        contractor_id=data.contractor_id,
        contractor_worker_id=data.contractor_worker_id,
        parent_id=data.parent_id,
        progress_percent=data.progress_percent,
        due_date=due_date,
        start_date=data.start_date,
        estimated_working_days=data.estimated_working_days,
    )

    # Отделы проверены ``department_rules`` (для вызывающего с ``scope``):
    # существование, активность и право. Отдел-отправитель главы, ставящего
    # задачу в чужой отдел, — связь ``origin`` (видит ход работ, прав нет).
    links = [TaskDepartmentLink(task=task, department_id=d) for d in dept_ids]
    if origin is not None and origin not in dept_ids:
        links.append(TaskDepartmentLink(task=task, department_id=origin,
                                        kind=DepartmentLinkKind.ORIGIN))
    if links:
        TaskDepartmentLink.objects.bulk_create(links)

    if data.label_ids:
        # Labels are local, so unknown ids are a client error we can detect —
        # keep only real ones, exactly as the original did.
        task.labels.set(Label.objects.filter(id__in=data.label_ids))

    # «Новая задача» (K-28): своё назначение видно сразу, назначенным другими
    # — новость, пока не откроют.
    now = timezone.now()
    TaskAssignee.objects.bulk_create(
        [TaskAssignee(task=task, user_id=uid, role=role,
                      seen_at=now if uid == user_id else None)
         for uid, role in crew]
    )

    task_notify.assignees_added(
        task, user_id, [uid for uid, _role in crew],
        primary_id=next((uid for uid, role in crew if role == AssigneeRole.PRIMARY), None))

    # Автоматизация досок (этап S4): создана, затем — с чем пришла.
    automation.emit(
        Event("card_created", task.pk, user_id, {"status": task.status}),
        *_crew_events(task, user_id, set(), {uid for uid, _role in crew}),
        _due_event(task, user_id, None, task.due_date),
        *[Event("label_added", task.pk, user_id, {"label_id": label_id})
          for label_id in sorted(task.labels.values_list("pk", flat=True))],
        (Event("supervisor_set", task.pk, user_id, {"user_id": task.supervisor_id})
         if task.supervisor_id else None))
    return task


@transaction.atomic
def update_task(task_id: int, data, user_id: int | None = None, *,
                scope=None) -> Task:
    """``scope`` — ``TaskScope`` вызывающего: правила отдела, автора и
    родителя (канбан K1.5). ``None`` — внутренний вызов без проверок.
    Строка блокируется: связи отделов пишут и перенос, и «Взять в работу» —
    под той же блокировкой (ревью K1.6)."""
    task = Task.objects.select_for_update().filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")

    changes = data.model_dump(exclude_unset=True)
    label_ids = changes.pop("label_ids", None)
    department_ids = changes.pop("department_ids", None)
    status_changed = False
    old_assignee_id = task.assignee_id
    old_status, old_due, old_supervisor = task.status, task.due_date, task.supervisor_id
    old_labels = set(task.labels.values_list("pk", flat=True)) if label_ids is not None else set()
    old_crew = _crew_ids(task) if "assignee_id" in changes else set()
    old_home = (task.department_id, task.project_id)

    slug = changes.pop("task_type", None)
    if slug is not None and "task_type_id" not in changes:
        changes["task_type_id"] = resolve_task_type_id(None, slug)

    # Setting the multi-department set also realigns the primary, unless the
    # caller set it explicitly in the same request.
    if department_ids is not None and "department_id" not in changes:
        changes["department_id"] = department_ids[0] if department_ids else None

    if scope is not None:
        _check_update(task, changes, department_ids, scope)

    # Объект и проект могут прийти в одном PATCH, поэтому решение принимаем
    # по итоговой паре, а не по присланным полям по отдельности. Если
    # меняется только проект, текущий объект всё равно перепроверяется: смена
    # проекта на такой, где объект не числится, это ошибка (400), а не
    # молчаливое обнуление — потерять привязку задним числом хуже, чем
    # получить отказ.
    # Роудмап первым: выбранный пакет работ ЗАДАЁТ проект, площадку И БЛОК,
    # поэтому его результат уходит в changes до проверок ниже.
    if "roadmap_id" in changes:
        project_id, site_id, block_id, roadmap_id = (
            roadmap_service.resolve_task_roadmap(
                changes.get("project_id", task.project_id),
                changes.get("site_id", task.site_id),
                changes.get("site_block_id", task.site_block_id),
                changes["roadmap_id"]))
        changes["roadmap_id"] = roadmap_id
        if roadmap_id is not None:
            changes["project_id"] = project_id
            changes["site_id"] = site_id
            changes["site_block_id"] = block_id

    if "project_id" in changes or "site_id" in changes:
        effective_project = changes.get("project_id", task.project_id)
        effective_site = changes.get("site_id", task.site_id)
        changes["site_id"] = site_service.resolve_task_site(
            effective_project, effective_site)

    # Блок проверяем ПОСЛЕ объекта и по уже вычисленному значению: в одном
    # PATCH могут приехать и объект, и блок, а правило связывает именно
    # итоговую пару. Блок без объекта задачи задаёт его сам — «блок 1»
    # однозначно называет площадку, которой принадлежит.
    if "site_block_id" in changes or "site_id" in changes:
        effective_site = changes.get("site_id", task.site_id)
        effective_block = changes.get("site_block_id", task.site_block_id)
        changes["site_block_id"] = site_service.resolve_task_block(
            effective_site, effective_block)
        if changes["site_block_id"] and effective_site is None:
            changes["site_id"] = site_service.block_site_id(
                changes["site_block_id"])

    if "status" in changes:
        target = changes.pop("status")
        # Запрет держат домашние доски задачи ПОСЛЕ правки: отдел или проект
        # могут смениться тем же PATCH (спецификация логики §5).
        preview = copy.copy(task)
        preview.department_id = changes.get("department_id", task.department_id)
        preview.project_id = changes.get("project_id", task.project_id)
        try:
            task.apply_transition(target)
        except ValueError as exc:
            # Invalid FSM edge -> the original's 400 — раньше запрета.
            raise ValueError(str(exc)) from exc
        # Ручной перенос, запрещённый правилом доски, — 409 до сохранения (K-38).
        automation.precheck_move(preview, old_status, task.status, user_id)
        # Смена статуса — ключевое событие ленты карточки (канбан-доски,
        # мастер-план §6.4; в Trello — «переместил карточку из списка в
        # список»). Прежний API её не журналировал ради паритета с FastAPI —
        # это решение снято вместе с досками.
        if old_status != task.status:
            _log(task, user_id, "status", old_status, task.status)
            status_changed = True

    for field_name in TRACKED_FIELDS:
        if field_name in changes:
            old = getattr(task, field_name)
            new = changes[field_name]
            if old != new:
                _log(task, user_id, field_name, old, new)

    for field, value in changes.items():
        setattr(task, field, value)
    # По СЛИТОЙ паре, а не по присланным полям: в PATCH может приехать
    # одна дата, вторая лежит в строке. Без этой проверки нарушение
    # доходит до CheckConstraint и возвращается как 500.
    date_rules.assert_instance_ordered(task)
    task.save()

    if "assignee_id" in changes:
        _sync_primary_assignee(task, changes["assignee_id"], actor_id=user_id)

    if label_ids is not None:
        task.labels.set(Label.objects.filter(id__in=label_ids))

    if department_ids is not None:
        # Набор отделов-участников заменяется целиком; отдел-отправитель
        # (``origin``) остаётся, а попав в новый набор, становится участником.
        task.department_links.filter(kind=DepartmentLinkKind.MEMBER).delete()
        for department_id in dict.fromkeys(department_ids):
            TaskDepartmentLink.objects.update_or_create(
                task=task, department_id=department_id,
                defaults={"kind": DepartmentLinkKind.MEMBER})

    # Уведомления — после всех правок: получатели — участники уже
    # изменённой задачи (K-29).
    if task.assignee_id != old_assignee_id:
        task_notify.primary_changed(task, user_id, task.assignee_id)
    if status_changed:
        task_notify.status_changed(task, user_id, task.status)

    # Автоматизация досок (этап S4) — после всех правок задачи.
    events = []
    if status_changed:
        events.append(Event("moved", task.pk, user_id, {"from": old_status, "to": task.status}))
    if label_ids is not None:
        new_labels = set(task.labels.values_list("pk", flat=True))
        events += [Event("label_added", task.pk, user_id, {"label_id": label_id})
                   for label_id in sorted(new_labels - old_labels)]
        events += [Event("label_removed", task.pk, user_id, {"label_id": label_id})
                   for label_id in sorted(old_labels - new_labels)]
    if "assignee_id" in changes:
        events += _crew_events(task, user_id, old_crew, _crew_ids(task))
    events.append(_due_event(task, user_id, old_due, task.due_date))
    if task.supervisor_id != old_supervisor:
        events.append(Event("supervisor_set" if task.supervisor_id else "supervisor_removed",
                            task.pk, user_id, {"user_id": task.supervisor_id}))
    if (task.department_id, task.project_id) != old_home:
        events += arrived_events(task, user_id, _home_keys(*old_home))
    automation.emit(*events)
    return task


def _home_keys(department_id: int | None, project_id: int | None) -> set:
    keys = set()
    if department_id:
        keys.add((BoardKind.DEPARTMENT, department_id))
    if project_id:
        keys.add((BoardKind.PROJECT, project_id))
    return keys


def _check_update(task: Task, changes: dict, department_ids, scope) -> None:
    """Проверки правки задачи по правам вызывающего (канбан K1.5)."""
    if ("reporter_id" in changes and not scope.elevated
            and changes["reporter_id"] != task.reporter_id):
        raise DomainError("task_reporter_forbidden",
                          "Автора задачи меняет только администратор", status=422)
    # Смена ОСНОВНОГО отдела проверяется всегда, даже если отдел уже стоит
    # связью-участником: иначе глава, создав задачу на свой и чужой отдел,
    # одной правкой сделал бы чужой основным — перенос без переноса (ревью
    # K1.5). Из прочих отделов — только новые: повторная отправка прежнего
    # набора (интерфейс шлёт форму целиком) не должна упираться в старые связи.
    current = {task.department_id} | {
        link.department_id for link in task.department_links.all()
        if link.kind == DepartmentLinkKind.MEMBER}
    checked = []
    new_primary = changes.get("department_id", task.department_id)
    if new_primary != task.department_id:
        checked.append(new_primary)
    checked += [d for d in (department_ids or []) if d not in current]
    checked = [d for d in dict.fromkeys(checked) if d is not None]
    if checked:
        department_rules.check_change(scope, task, checked)
    parent_id = changes.get("parent_id")
    if parent_id is not None and parent_id != task.parent_id:
        get_task(parent_id, scope=scope)                 # невидимый родитель — 404 (S1-18)


def _sync_primary_assignee(task: Task, new_primary_id: int | None, *,
                           actor_id: int | None = None) -> None:
    """Keep ``TaskAssignee`` consistent after the legacy scalar changed.
    Новая строка — «новая задача» для назначенного, если он назначил не сам
    себя (K-28)."""
    task.assignees.filter(role=AssigneeRole.PRIMARY).exclude(
        user_id=new_primary_id
    ).update(role=AssigneeRole.COLLABORATOR)
    if new_primary_id is None:
        return
    row = task.assignees.filter(user_id=new_primary_id).first()
    if row is not None:
        row.role = AssigneeRole.PRIMARY
        row.save(update_fields=["role"])
    else:
        TaskAssignee.objects.create(
            task=task, user_id=new_primary_id, role=AssigneeRole.PRIMARY,
            seen_at=timezone.now() if new_primary_id == actor_id else None)


def delete_task(task_id: int) -> None:
    """Soft delete — the row stays for history and the ETL."""
    updated = Task.objects.filter(pk=task_id, is_deleted=False).update(
        is_deleted=True, updated_at=timezone.now()
    )
    if not updated:
        raise Http404("Task not found")


def available_transitions(task: Task) -> list[str]:
    """Statuses reachable from ``task``'s current one.

    Takes an already-loaded task: every caller reaches this through
    ``load_for_action``, which has already resolved the row AND checked
    visibility. Re-fetching here would mean a second query and a second,
    visibility-blind 404 branch.
    """
    return list(TRANSITIONS.get(task.status, frozenset()))


# ── participants ────────────────────────────────────────────────────────

@transaction.atomic
def replace_assignees(task_id: int, assignments: list,
                      actor_id: int | None) -> Task:
    """Atomically replace the crew — anyone not in the list is removed."""
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")

    existing = {row.user_id: row for row in task.assignees.all()}
    new_ids = {a.user_id for a in assignments}
    added = []
    before = _crew_ids(task)

    task.assignees.exclude(user_id__in=new_ids).delete()

    for a in assignments:
        row = existing.get(a.user_id)
        if row is not None:
            if row.role != a.role:
                row.role = a.role
                row.save(update_fields=["role"])
        else:
            # Повторное назначение снятого раньше человека — снова новость (K-28).
            TaskAssignee.objects.create(
                task=task, user_id=a.user_id, role=a.role,
                seen_at=timezone.now() if a.user_id == actor_id else None)
            added.append(a.user_id)

    primary = next((a.user_id for a in assignments
                    if a.role == AssigneeRole.PRIMARY), None)
    primary_changed = task.assignee_id != primary
    if primary_changed:
        _log(task, actor_id, "assignee_id", task.assignee_id, primary)
        task.assignee_id = primary
        task.save(update_fields=["assignee_id", "updated_at"])
    task_notify.assignees_added(task, actor_id, added, primary_id=primary)
    if primary_changed and primary not in added:
        task_notify.primary_changed(task, actor_id, primary)
    automation.emit(*_crew_events(task, actor_id, before, _crew_ids(task)))
    return task


@transaction.atomic
def set_supervisor(task_id: int, supervisor_id: int | None,
                   actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    if task.supervisor_id == supervisor_id:
        return task

    _log(task, actor_id, "supervisor_id", task.supervisor_id, supervisor_id)
    task.supervisor_id = supervisor_id
    task.save(update_fields=["supervisor_id", "updated_at"])
    task_notify.supervisor_set(task, actor_id, supervisor_id)
    automation.emit(Event("supervisor_set" if supervisor_id else "supervisor_removed",
                          task.pk, actor_id, {"user_id": supervisor_id}))
    return task


@transaction.atomic
def add_delegate(task_id: int, user_id: int, granted_by: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    if task.delegates.filter(user_id=user_id).exists():
        return task  # idempotent

    TaskDelegate.objects.create(task=task, user_id=user_id,
                                granted_by_id=granted_by)
    _log(task, granted_by, "delegates", None, f"+{user_id}")
    task_notify.delegated(task, granted_by, user_id)
    return task


@transaction.atomic
def remove_delegate(task_id: int, user_id: int, actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    deleted, _ = task.delegates.filter(user_id=user_id).delete()
    if deleted:
        _log(task, actor_id, "delegates", user_id, None)
    return task


def add_watcher(task_id: int, user_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    TaskWatcher.objects.get_or_create(task=task, user_id=user_id)
    return task


def remove_watcher(task_id: int, user_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    task.watchers.filter(user_id=user_id).delete()
    return task


@transaction.atomic
def set_progress(task_id: int, percent: int, actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    percent = max(0, min(100, int(percent)))
    if task.progress_percent == percent:
        return task
    _log(task, actor_id, "progress_percent", task.progress_percent, percent)
    task.progress_percent = percent
    task.save(update_fields=["progress_percent", "updated_at"])
    return task


# ─────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────

def task_stats(*, department_id=None, project_id=None, site_id=None,
               visibility_condition=None) -> dict:
    """``visibility_condition`` — ``report_visibility_q(token)``: у статистики
    своё, прежнее правило видимости (S1-11)."""
    qs = filtered_tasks(department_id=department_id, project_id=project_id,
                        site_id=site_id, legacy_q=visibility_condition)

    total = qs.count()

    # Every aggregate below counts DISTINCT ids on purpose. ``filtered_tasks``
    # joins across to-many tables (assignees/delegates/watchers/labels) for
    # the visibility rules, which multiplies rows per task; ``.distinct()``
    # dedupes the *rows* a list endpoint returns but does NOT dedupe inside a
    # GROUP BY, so a plain Count("id") would report a task once per role the
    # caller holds on it.
    n = Count("id", distinct=True)

    by_status = {row["status"]: row["n"] for row in
                 qs.values("status").annotate(n=n)}
    by_priority = {row["priority"]: row["n"] for row in
                   qs.values("priority").annotate(n=n)}
    # NULL task_type buckets under the literal 'unknown' so the response
    # stays dict[str, int], as the original declared.
    by_type = {(row["task_type__slug"] or "unknown"): row["n"] for row in
               qs.values("task_type__slug").annotate(n=n)}

    since = timezone.localdate() - timedelta(days=30)
    created_per_day = [
        {"day": str(row["day"]), "count": row["n"]}
        for row in (qs.filter(created_at__date__gte=since)
                    .values(day=TruncDate("created_at"))
                    .annotate(n=n).order_by("day"))
    ]
    resolved_per_day = [
        {"day": str(row["day"]), "count": row["n"]}
        for row in (qs.filter(completed_at__isnull=False,
                              completed_at__date__gte=since)
                    .values(day=TruncDate("completed_at"))
                    .annotate(n=n).order_by("day"))
    ]

    dept_rows = list(qs.values("department_id").annotate(n=n).order_by("-n"))
    dept_names = hydration.department_briefs(
        [row["department_id"] for row in dept_rows]
    )
    by_department = [
        {
            "department__id": row["department_id"],
            "department__name": hydration.department_name(
                dept_names, row["department_id"]) or "Без отдела",
            "count": row["n"],
        }
        for row in dept_rows
    ]

    # Проект и объект — свои модели этого же аппа, так что имена берутся
    # джойном, а не батчем через hydration (в отличие от отделов выше, где
    # строки принадлежат hr). NULL — полноценная корзина, а не пропуск:
    # задачи без проекта/объекта существуют законно и должны быть видны в
    # отчёте, иначе сумма разрезов не сойдётся с total.
    project_rows = list(qs.values("project_id", "project__name")
                        .annotate(n=n).order_by("-n"))
    by_project = [
        {
            "project__id": row["project_id"],
            "project__name": row["project__name"] or "Без проекта",
            "count": row["n"],
        }
        for row in project_rows
    ]

    site_rows = list(qs.values("site_id", "site__name", "site__color")
                     .annotate(n=n).order_by("-n"))
    by_site = [
        {
            "site__id": row["site_id"],
            "site__name": row["site__name"] or "Без объекта",
            "site__color": row["site__color"],
            "count": row["n"],
        }
        for row in site_rows
    ]

    assignee_rows = list(qs.filter(assignee_id__isnull=False)
                         .values("assignee_id").annotate(n=n).order_by("-n"))
    user_briefs = hydration.user_briefs(
        [row["assignee_id"] for row in assignee_rows]
    )
    by_assignee = []
    for row in assignee_rows:
        brief = user_briefs.get(row["assignee_id"], {})
        # The original exposed first/last name separately, straight off the
        # replica columns. The users brief only offers a composed
        # ``full_name``, so it is split back on the first space — the
        # frontend joins these two fields for display anyway.
        full = brief.get("full_name") or ""
        first, _, last = full.partition(" ")
        by_assignee.append({
            "assignee__id": row["assignee_id"],
            "assignee__first_name": first,
            "assignee__last_name": last,
            "assignee__username": brief.get("username") or "",
            "count": row["n"],
        })

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_type": by_type,
        "by_department": by_department,
        "by_project": by_project,
        "by_site": by_site,
        "by_assignee": by_assignee,
        "created_per_day": created_per_day,
        "resolved_per_day": resolved_per_day,
    }
