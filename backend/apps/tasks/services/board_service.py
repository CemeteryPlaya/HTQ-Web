"""Канбан-доски: состав, карточки, перенос и порядок (мастер-план §5–§6.1, этап S1).

Доска — не модель, а запрос над задачами (K-01) с ключом «вид + id»:
личная — задачи, где пользователь участник (K-03); доска отдела — задачи
поддерева отдела (K-04); доска проекта — задачи ``tasks.Project``. Видимость
всегда ``Visible(u) & условие доски`` (§5.2): всё, что видно на доске, открывает
и ``load_for_action``.

Колонка — статус задачи (K-02); доска лишь задаёт колонкам свои названия,
цвета и скрытость (``BoardSettings``, решение K-34). Порядок внутри колонки —
``BoardCardRank`` (§3.2): ранги — свойство доски, а не того, кто на неё
смотрит, поэтому считаются по всем задачам доски, без фильтра видимости.

Сборка доски — одна выборка задач с подзапросами-счётчиками (а не джойнами:
``visibility_q`` и так множит строки), окно ``ROW_NUMBER`` режет колонку до
``COLUMN_LIMIT``; имена людей и отделов — батчами через соседские ``interface``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Window
from django.db.models.functions import Coalesce, Collate, RowNumber
from django.http import Http404
from django.utils import timezone

from apps.access import interface as access
from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from htqweb.errors import DomainError
from htqweb.fallback import fallback
from htqweb.tenancy.context import current_company_or_none

from .. import schemas
from ..models import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    BoardCardRank,
    BoardKind,
    BoardSettings,
    DepartmentLinkKind,
    Project,
    Status,
    Task,
    TaskAssignee,
    TaskAttachment,
    TaskComment,
)
from . import board_rank
from . import board_scope
from . import hydration
from . import project_service
from . import task_scope
from . import task_service

#: Порядок колонок слева направо.
COLUMN_ORDER = (
    Status.BACKLOG, Status.TODO, Status.IN_PROGRESS, Status.IN_REVIEW,
    Status.BLOCKED, Status.DONE, Status.CANCELLED,
)
#: Карточек в колонке за один ответ; дальше — ``?status=&offset=``.
COLUMN_LIMIT = 200
#: Палитра цветов колонок — как в Trello; на фронте — токены ``--board-color-*``.
PALETTE = ("green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "gray")
#: Узел «Доски: настройки, поля и автоматизация» (решение K-39).
ADMIN_NODE = "tasks.boards.admin"
#: Сколько дней по умолчанию показывать завершённые и отменённые (K-26).
DEFAULT_DONE_DAYS = 30


@dataclass(frozen=True)
class Board:
    kind: str
    id: int
    title: str | None = None
    #: Поддерево отдела — у доски отдела.
    department_ids: tuple[int, ...] = ()
    project: Project | None = None


# ── какая доска и можно ли её открыть ──────────────────────────────────

def personal(request) -> Board:
    """Личная доска — только своя: владелец берётся из токена (§5.4)."""
    return Board(kind=BoardKind.PERSONAL, id=request.token.user_id)


def department(request, department_id: int) -> Board:
    """Доска отдела с поддеревом. Нет доступа или отдела — 404 (§5.2)."""
    scope = task_scope.for_request(request)
    allowed = (scope.elevated or scope.all_departments
               or department_id in scope.department_ids)
    if not allowed:
        raise Http404("Board not found")
    brief = hr.get_department_brief(department_id)          # hr выключен — 503
    if brief is None:
        raise Http404("Board not found")
    subtree = hr.department_subtree_ids([department_id]).get(department_id) or [department_id]
    return Board(kind=BoardKind.DEPARTMENT, id=department_id, title=brief["name"],
                 department_ids=tuple(subtree))


def project(request, project_id: int) -> Board:
    """Доска проекта задач — если видна по тем же правилам, что и список
    досок (``project_service``)."""
    employee_scope, department_ids = project_service.scope_for(request)
    found = project_service.get_project(
        project_id, employee_scope=employee_scope, department_ids=department_ids,
        refs=board_scope.refs_for_request(request))
    return Board(kind=BoardKind.PROJECT, id=found.id, title=found.name, project=found)


def resolve(request, kind: str, board_id: int | None) -> Board:
    if kind == BoardKind.PERSONAL:
        return personal(request)
    if board_id is None:
        raise Http404("Board not found")
    if kind == BoardKind.DEPARTMENT:
        return department(request, board_id)
    if kind == BoardKind.PROJECT:
        return project(request, board_id)
    raise Http404("Board not found")


def is_admin(request, board: Board) -> bool:
    """Правит настройки доски (K-39): личная — владелец; отдела — глава отдела
    (или вышестоящего); проекта — владелец проекта задач; плюс держатель узла
    ``tasks.boards.admin`` и администратор задач."""
    scope = task_scope.for_request(request)
    if board.kind == BoardKind.PERSONAL or scope.elevated:
        return True
    if board.kind == BoardKind.DEPARTMENT and board.id in scope.managed_subtree:
        return True
    if (board.kind == BoardKind.PROJECT and board.project is not None
            and board.project.owner_id == scope.user_id):
        return True
    return "edit" in access.flags_for(request.token, ADMIN_NODE, current_company_or_none())


def require_admin(request, board: Board) -> None:
    if not is_admin(request, board):
        raise PermissionDenied("Настройки доски меняет её администратор")


# ── выборка задач доски ─────────────────────────────────────────────────

def _board_condition(board: Board) -> Q:
    if board.kind == BoardKind.PERSONAL:
        return task_service.participant_q(board.id)
    if board.kind == BoardKind.DEPARTMENT:
        return task_service.department_q(board.department_ids)
    return Q(project_id=board.id)


def board_tasks(board: Board, scope=None):
    """Задачи доски, видимые ``scope`` (``None`` — все задачи доски: для
    рангов). Внутренний запрос — только id: джойны видимости не множат строки
    внешнего запроса."""
    inner = Task.objects.filter(is_deleted=False).filter(_board_condition(board))
    visibility = task_service.visibility_q(scope)
    if visibility is not None:
        inner = inner.filter(visibility)
    return Task.objects.filter(pk__in=inner.values("pk"))


@dataclass(frozen=True)
class Filters:
    """Фильтры доски (как фильтр Trello). Внутри группы — «или», между
    группами — «и». ``done_days`` режет завершённые и отменённые (K-26)."""

    q: str = ""
    labels: tuple[str, ...] = ()        # id меток и ``none``
    members: tuple[str, ...] = ()       # id людей, ``me`` и ``none``
    due: tuple[str, ...] = ()           # overdue, day, week, month, none
    completion: tuple[str, ...] = ()    # complete, incomplete
    activity: tuple[str, ...] = ()      # 1w, 2w, 4w, stale4w
    new_only: bool = False
    done_days: int = DEFAULT_DONE_DAYS
    status: str | None = None           # дозагрузка одной колонки
    offset: int = 0
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_query(cls, params) -> "Filters":
        def many(name: str) -> tuple[str, ...]:
            values = []
            for raw in params.getlist(name):
                values.extend(part.strip() for part in raw.split(",") if part.strip())
            return tuple(dict.fromkeys(values))

        def number(name: str, default: int) -> int:
            raw = (params.get(name) or "").strip()
            if not raw:
                return default
            try:
                return max(0, int(raw))
            except ValueError as exc:
                raise DomainError("board_filter_invalid", f"Параметр {name} — число",
                                  status=422) from exc

        status = (params.get("status") or "").strip() or None
        if status is not None and status not in Status.values:
            raise DomainError("board_filter_invalid", "Неизвестная колонка", status=422)
        return cls(
            q=(params.get("q") or "").strip(),
            labels=many("label"), members=many("member"), due=many("due"),
            completion=many("completion"), activity=many("activity"),
            new_only=(params.get("new") or "") in ("1", "true"),
            done_days=number("done_days", DEFAULT_DONE_DAYS),
            status=status, offset=number("offset", 0),
        )


def _ids(values) -> list[int]:
    return [int(value) for value in values if value.isdigit()]


def _apply_filters(qs, filters: Filters, board: Board, scope):
    if filters.q:
        qs = qs.filter(Q(summary__icontains=filters.q) | Q(key__icontains=filters.q))
    if filters.labels:
        label_link = Task.labels.through.objects.filter(task_id=OuterRef("pk"))
        cond = Q()
        if ids := _ids(filters.labels):
            cond |= Exists(label_link.filter(label_id__in=ids))
        if "none" in filters.labels:
            cond |= ~Exists(label_link)
        qs = qs.filter(cond)
    if filters.members:
        rows = TaskAssignee.objects.filter(task=OuterRef("pk"))
        ids = _ids(filters.members)
        if "me" in filters.members:
            ids.append(scope.user_id)
        cond = Q()
        if ids:
            cond |= Q(assignee_id__in=ids) | Exists(rows.filter(user_id__in=ids))
        if "none" in filters.members:
            cond |= Q(assignee_id__isnull=True) & ~Exists(rows)
        qs = qs.filter(cond)
    if filters.due:
        today = timezone.localdate()
        open_ = ~Q(status__in=list(TERMINAL_STATUSES))
        cond = Q()
        spans = {"day": 1, "week": 7, "month": 30}
        for key in filters.due:
            if key == "none":
                cond |= Q(due_date__isnull=True)
            elif key == "overdue":
                cond |= Q(due_date__lt=today) & open_
            elif key in spans:
                cond |= Q(due_date__gte=today, due_date__lte=today + timedelta(days=spans[key])) & open_
        qs = qs.filter(cond)
    if filters.completion and len(set(filters.completion) & {"complete", "incomplete"}) == 1:
        done = Q(status=Status.DONE)
        qs = qs.filter(done if "complete" in filters.completion else ~done)
    if filters.activity:
        now = timezone.now()
        cond = Q()
        for key in filters.activity:
            if key in ("1w", "2w", "4w"):
                cond |= Q(updated_at__gte=now - timedelta(weeks=int(key[0])))
            elif key == "stale4w":
                cond |= Q(updated_at__lt=now - timedelta(weeks=4))
        qs = qs.filter(cond)
    if filters.new_only and board.kind == BoardKind.PERSONAL:
        qs = qs.filter(Exists(TaskAssignee.objects.filter(
            task=OuterRef("pk"), user_id=board.id, seen_at__isnull=True)))
    if filters.done_days:
        # Завершённые давно — не на доске (K-26). У старых задач без
        # ``completed_at`` (отметка появилась позже них) — по последней правке.
        since = timezone.now() - timedelta(days=filters.done_days)
        stale = (Q(completed_at__lt=since)
                 | Q(completed_at__isnull=True, updated_at__lt=since))
        qs = qs.exclude(Q(status__in=list(TERMINAL_STATUSES)) & stale)
    return qs


def _count(model, **lookup):
    return Coalesce(Subquery(
        model.objects.filter(task=OuterRef("pk"), **lookup).order_by()
        .values("task").annotate(n=Count("pk")).values("n")[:1]), 0)


def _rank_subquery(board: Board):
    return Subquery(BoardCardRank.objects.filter(
        board_kind=board.kind, board_id=board.id, task=OuterRef("pk")).values("rank")[:1])


def _column_order():
    return [Collate(F("board_rank"), "C").asc(nulls_last=True),
            F("created_at").desc(), F("pk").desc()]


def _annotated(qs, board: Board):
    qs = qs.annotate(
        board_rank=_rank_subquery(board),
        comments_count=_count(TaskComment),
        attachments_count=_count(TaskAttachment),
    )
    if board.kind == BoardKind.PERSONAL:
        qs = qs.annotate(is_new=Exists(TaskAssignee.objects.filter(
            task=OuterRef("pk"), user_id=board.id, seen_at__isnull=True)))
    return (qs.select_related("project")
            .prefetch_related("labels", "assignees", "delegates", "watchers",
                              "department_links"))


# ── карточка ────────────────────────────────────────────────────────────

def _can_progress(task: Task, scope) -> bool:
    """``task_service.can_progress`` по уже загруженным связям — без запроса
    на карточку."""
    if scope.elevated:
        return True
    uid = scope.user_id
    if uid in (task.reporter_id, task.supervisor_id, task.assignee_id):
        return True
    if task_service.is_head_of(task, scope):
        return True
    if any(row.user_id == uid for row in task.delegates.all()):
        return True
    return any(row.user_id == uid for row in task.assignees.all())


def _relation(task: Task, board: Board) -> str | None:
    """Чем задача связана с доской отдела: основной отдел, связь-участник или
    только отправитель (§5.2)."""
    if board.kind != BoardKind.DEPARTMENT:
        return None
    subtree = set(board.department_ids)
    if task.department_id in subtree:
        return "own"
    kinds = {link.kind for link in task.department_links.all() if link.department_id in subtree}
    if DepartmentLinkKind.MEMBER in kinds:
        return "linked"
    return "sent" if kinds else None


def _my_role(task: Task, user_id: int) -> str | None:
    """Старшая роль владельца личной доски в задаче (§5.2)."""
    if task.assignee_id == user_id or any(row.user_id == user_id for row in task.assignees.all()):
        return "assignee"
    if task.supervisor_id == user_id:
        return "supervisor"
    if task.reporter_id == user_id:
        return "reporter"
    if any(row.user_id == user_id for row in task.delegates.all()):
        return "delegate"
    if any(row.user_id == user_id for row in task.watchers.all()):
        return "watcher"
    return None


class _Ctx:
    def __init__(self, tasks: list[Task]):
        user_ids, department_ids = set(), set()
        for task in tasks:
            user_ids.update(row.user_id for row in task.assignees.all())
            if task.assignee_id:
                user_ids.add(task.assignee_id)
            if task.department_id:
                department_ids.add(task.department_id)
        self.users = hydration.user_briefs(user_ids)
        self.departments = hydration.department_briefs(department_ids)


def _members(task: Task, ctx: _Ctx) -> list[dict]:
    rows = sorted(task.assignees.all(),
                  key=lambda row: (row.role != "primary", row.assigned_at, row.user_id))
    members = [{"user_id": row.user_id, "role": row.role} for row in rows]
    if task.assignee_id and all(m["user_id"] != task.assignee_id for m in members):
        members.insert(0, {"user_id": task.assignee_id, "role": "primary"})
    for member in members:
        member["name"] = hydration.user_name(ctx.users, member["user_id"])
        member["avatar_url"] = hydration.user_avatar(ctx.users, member["user_id"])
    return members


def card(task: Task, board: Board, scope, ctx: _Ctx) -> dict:
    """Облегчённая карточка (§6.1), не ``build_detail``."""
    personal_board = board.kind == BoardKind.PERSONAL
    return {
        "id": task.id,
        "key": task.key,
        "summary": task.summary,
        "status": task.status,
        "priority": task.priority,
        "labels": [{"id": label.id, "name": label.name, "color": label.color}
                   for label in sorted(task.labels.all(), key=lambda lb: lb.name)],
        "due_date": task.due_date,
        "start_date": task.start_date,
        "completed_at": task.completed_at,
        "progress_percent": task.progress_percent,
        "has_description": bool((task.description or "").strip()),
        "counts": {
            "comments": task.comments_count,
            "attachments": task.attachments_count,
            # Чек-листы — этап S2 (``tasks/0031``).
            "checklist_done": 0,
            "checklist_total": 0,
        },
        "members": _members(task, ctx),
        "project": ({"id": task.project.id, "name": task.project.name,
                     "color": task.project.color} if task.project_id else None),
        "department": ({"id": task.department_id,
                        "name": hydration.department_name(ctx.departments, task.department_id)}
                       if task.department_id else None),
        "relation": _relation(task, board),
        "rank": task.board_rank,
        # «Новая» — только на своей личной доске (K-28): на досках отделов и
        # проектов не раскрываем, открыл ли задачу другой человек.
        "is_new": bool(getattr(task, "is_new", False)) if personal_board else False,
        "my_role": _my_role(task, board.id) if personal_board else None,
        "can_move": _can_progress(task, scope),
    }


# ── доска целиком ───────────────────────────────────────────────────────

def _settings_row(board: Board) -> BoardSettings | None:
    return BoardSettings.objects.filter(board_kind=board.kind, board_id=board.id).first()


def columns_settings(board: Board) -> dict:
    row = _settings_row(board)
    stored = row.columns if row is not None else {}
    return {
        status: {
            "title": (stored.get(status) or {}).get("title") or None,
            "color": (stored.get(status) or {}).get("color") or None,
            "hidden": bool((stored.get(status) or {}).get("hidden")),
        }
        for status in COLUMN_ORDER
    }


def can_create(request, board: Board) -> bool:
    """Быстрое добавление: на доске отдела рядовой ставит задачи в своё
    поддерево, глава — в любой отдел (``department_rules``), ОД и ГД, видящие
    все отделы, — только как участники своих отделов."""
    if board.kind != BoardKind.DEPARTMENT:
        return True
    scope = task_scope.for_request(request)
    return (scope.elevated or bool(scope.managed_ids)
            or board.id in scope.department_ids)


def build_board(request, board: Board, filters: Filters) -> dict:
    scope = task_scope.for_request(request)
    settings = columns_settings(board)
    shown = [status for status in COLUMN_ORDER if not settings[status]["hidden"]]
    base = _apply_filters(board_tasks(board, scope), filters, board, scope)

    counts = dict(base.order_by().values_list("status").annotate(n=Count("pk")))

    statuses = [filters.status] if filters.status else shown
    rows = (_annotated(base.filter(status__in=statuses), board)
            .annotate(column_row=Window(RowNumber(), partition_by=[F("status")],
                                        order_by=_column_order()))
            .filter(column_row__gt=filters.offset,
                    column_row__lte=filters.offset + COLUMN_LIMIT + 1)
            .order_by("status", "column_row"))
    tasks = list(rows)
    ctx = _Ctx(tasks)
    by_status: dict[str, list[Task]] = {}
    for task in tasks:
        by_status.setdefault(task.status, []).append(task)

    columns = []
    for status in COLUMN_ORDER:
        if filters.status and status != filters.status:
            continue
        column_tasks = by_status.get(status, [])
        columns.append({
            "status": status,
            **settings[status],
            "count": counts.get(status, 0),
            "cards": [card(task, board, scope, ctx) for task in column_tasks[:COLUMN_LIMIT]],
            "has_more": len(column_tasks) > COLUMN_LIMIT,
        })

    admin = is_admin(request, board)
    return {
        "board": {
            "kind": board.kind,
            "id": None if board.kind == BoardKind.PERSONAL else board.id,
            "title": board.title,
            "color": board.project.color if board.project is not None else None,
            "settings": {"columns": settings},
        },
        "columns": columns,
        "can": {
            "admin": admin,
            # Порядок в колонке без смены статуса: глава отдела доски,
            # владелец проекта, владелец личной доски — у любой карточки; прочие
            # — у карточек с ``can_move`` (§5.3).
            "reorder": admin,
            "create": can_create(request, board),
        },
    }


def card_for(request, board: Board, task_id: int) -> dict:
    """Одна карточка в том же виде, что на доске, — ответ переноса и быстрого
    добавления."""
    scope = task_scope.for_request(request)
    task = _annotated(board_tasks(board, scope).filter(pk=task_id), board).first()
    if task is None:
        raise Http404("Task not found")
    return card(task, board, scope, _Ctx([task]))


# ── порядок карточек ────────────────────────────────────────────────────

def _lock(board: Board) -> None:
    """Ранги доски пишутся по очереди: вставки в одну колонку от двух людей
    иначе получили бы один и тот же ранг."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                       [f"tasks.board:{board.kind}:{board.id}"])


def _column(board: Board, status: str) -> list[tuple[int, str | None]]:
    """Задачи колонки доски в порядке показа: ``(id, ранг)``."""
    rows = (board_tasks(board).filter(status=status)
            .annotate(board_rank=_rank_subquery(board))
            .order_by(*_column_order())
            .values_list("pk", "board_rank"))
    return list(rows)


def _write_ranks(board: Board, ranks: dict[int, str]) -> None:
    existing = {row.task_id: row for row in BoardCardRank.objects.filter(
        board_kind=board.kind, board_id=board.id, task_id__in=list(ranks))}
    changed, created = [], []
    for task_id, rank in ranks.items():
        row = existing.get(task_id)
        if row is None:
            created.append(BoardCardRank(board_kind=board.kind, board_id=board.id,
                                         task_id=task_id, rank=rank))
        elif row.rank != rank:
            row.rank = rank
            changed.append(row)
    if created:
        BoardCardRank.objects.bulk_create(created)
    if changed:
        BoardCardRank.objects.bulk_update(changed, ["rank", "updated_at"])


def _ranked_column(board: Board, status: str, exclude: int | None = None) -> list[tuple[int, str]]:
    """Колонка с рангами у каждой карточки. Карточки без строки впервые
    получают ранги — колонка раскладывается заново в текущем порядке показа
    (один раз; бэкфилла нет, §3.2)."""
    column = [(pk, rank) for pk, rank in _column(board, status) if pk != exclude]
    if any(rank is None for _pk, rank in column) or any(
            board_rank.needs_rebalance(rank) for _pk, rank in column if rank):
        fresh = board_rank.spread(len(column))
        column = [(pk, fresh[index]) for index, (pk, _rank) in enumerate(column)]
        _write_ranks(board, dict(column))
    return column


def _stale(message: str) -> DomainError:
    return DomainError("board_order_stale", message, status=409)


def _rank_between(board: Board, status: str, task_id: int,
                  before_id: int | None, after_id: int | None) -> str:
    """Ранг карточки между соседями. Соседи — по ту и другую сторону места
    вставки в ЦЕЛЕВОЙ колонке; сосед не из неё — 409: клиент перечитывает
    колонку."""
    column = _ranked_column(board, status, exclude=task_id)
    ranks = dict(column)
    order = [pk for pk, _rank in column]
    if before_id is None and after_id is None:
        # Без соседей — в конец колонки.
        return board_rank.between(column[-1][1] if column else None, None)
    for neighbour in (before_id, after_id):
        if neighbour is not None and neighbour not in ranks:
            raise _stale("Колонка изменилась — обновите доску и повторите")
    if before_id is not None and after_id is not None:
        if order.index(after_id) != order.index(before_id) + 1:
            raise _stale("Колонка изменилась — обновите доску и повторите")
        return board_rank.between(ranks[before_id], ranks[after_id])
    if before_id is not None:
        position = order.index(before_id)
        nxt = ranks[order[position + 1]] if position + 1 < len(order) else None
        return board_rank.between(ranks[before_id], nxt)
    position = order.index(after_id)
    prev = ranks[order[position - 1]] if position > 0 else None
    return board_rank.between(prev, ranks[after_id])


def _store_rank(board: Board, status: str, task_id: int, rank: str) -> None:
    _write_ranks(board, {task_id: rank})
    if board_rank.needs_rebalance(rank):
        _ranked_column(board, status)


def can_reorder(request, board: Board, task: Task) -> bool:
    """Порядок без смены статуса (§5.3): владелец личной доски, глава отдела
    доски и владелец проекта — у любой карточки; прочие — если вправе вести
    задачу (``require_soft_edit``)."""
    scope = task_scope.for_request(request)
    if board.kind == BoardKind.PERSONAL or scope.elevated:
        return True
    if board.kind == BoardKind.DEPARTMENT and board.id in scope.managed_subtree:
        return True
    if (board.kind == BoardKind.PROJECT and board.project is not None
            and board.project.owner_id == scope.user_id):
        return True
    return task_service.can_progress(task, scope)


@transaction.atomic
def move(request, task_id: int, data: schemas.CardMove) -> dict:
    """Перенос карточки: смена колонки (статуса) и место в колонке (§6.1).

    Видимость — ``load_for_action`` (404); задача не на этой доске — 404;
    смена статуса — ``require_soft_edit`` и схема переходов (400
    ``task_transition_invalid`` со списком допустимых); только порядок —
    ``can_reorder`` (403); соседи не из целевой колонки — 409
    ``board_order_stale``.
    """
    board = resolve(request, data.board.kind, data.board.id)
    task = task_service.load_for_action(task_id, request)
    if not board_tasks(board).filter(pk=task_id).exists():
        raise Http404("Task not found")
    target = data.status
    if target != task.status:
        task_service.require_soft_edit(task, request)
        allowed = sorted(TRANSITIONS.get(task.status, frozenset()))
        if target not in allowed:
            raise DomainError("task_transition_invalid",
                              "Так перенести задачу нельзя", status=400,
                              details={"allowed": allowed})
    elif not can_reorder(request, board, task):
        raise PermissionDenied("Порядок карточек меняет участник задачи или администратор доски")

    _lock(board)
    rank = _rank_between(board, target, task_id, data.before_id, data.after_id)
    if target != task.status:
        task_service.update_task(task_id, schemas.TaskUpdate(status=target),
                                 user_id=request.token.user_id,
                                 scope=task_scope.for_request(request))
    _store_rank(board, target, task_id, rank)
    return card_for(request, board, task_id)


def place_new(board: Board, task: Task) -> None:
    """Быстрое добавление: новая задача — в конец своей колонки на доске."""
    _lock(board)
    column = _ranked_column(board, task.status, exclude=task.id)
    rank = board_rank.between(column[-1][1] if column else None, None)
    _store_rank(board, task.status, task.id, rank)


def place_on_department(department_id: int, task: Task) -> None:
    """Задача пришла в отдел — в конец её колонки на доске этого отдела (с
    поддеревом: так её видит доска). ``hr`` выключен — только сам отдел."""
    try:
        subtree = hr.department_subtree_ids([department_id]).get(department_id)
    except ServiceDisabled as exc:
        subtree = fallback("tasks.board_service.subtree_unavailable", None,
                           reason="hr выключен — место на доске только по самому отделу",
                           expected=True, exc=exc)
    place_new(Board(kind=BoardKind.DEPARTMENT, id=department_id,
                    department_ids=tuple(subtree or [department_id])), task)


def forget_department_ranks(task_id: int) -> None:
    """Задача ушла в другой отдел — её места на досках отделов больше не
    действуют (§5.5, шаг 7)."""
    BoardCardRank.objects.filter(task_id=task_id, board_kind=BoardKind.DEPARTMENT).delete()


# ── «новая задача» и сводка профиля ────────────────────────────────────

def mark_seen(request, task_id: int) -> None:
    """Открыл задачу — она больше не «новая» (K-28). Идемпотентно, в журнал
    не пишется; невидимая задача — 404."""
    task_service.load_for_action(task_id, request)
    TaskAssignee.objects.filter(task_id=task_id, user_id=request.token.user_id,
                                seen_at__isnull=True).update(seen_at=timezone.now())


def personal_summary(request) -> dict:
    """Блок «Мои задачи» в профиле (K-27): новые, ближайшие по сроку,
    счётчики колонок и просроченные."""
    scope = task_scope.for_request(request)
    board = personal(request)
    base = board_tasks(board, scope)
    open_ = ~Q(status__in=list(TERMINAL_STATUSES))
    today = timezone.localdate()

    mine_unseen = TaskAssignee.objects.filter(task=OuterRef("pk"), user_id=board.id,
                                              seen_at__isnull=True)
    new = (_annotated(base.filter(Exists(mine_unseen)), board)
           .annotate(my_assigned_at=Subquery(mine_unseen.values("assigned_at")[:1]))
           .order_by(F("my_assigned_at").desc(nulls_last=True), "-pk"))
    upcoming = (_annotated(base.filter(status__in=[Status.TODO, Status.IN_PROGRESS,
                                                  Status.IN_REVIEW]), board)
                .order_by(F("due_date").asc(nulls_last=True), "-created_at"))
    new_list, upcoming_list = list(new[:5]), list(upcoming[:5])
    ctx = _Ctx(new_list + upcoming_list)
    counts = dict(base.order_by().values_list("status").annotate(n=Count("pk")))
    return {
        "new": [card(task, board, scope, ctx) for task in new_list],
        "new_count": base.filter(Exists(mine_unseen)).count(),
        "upcoming": [card(task, board, scope, ctx) for task in upcoming_list],
        "columns": [{"status": status, "count": counts.get(status, 0)}
                    for status in COLUMN_ORDER],
        "overdue_count": base.filter(open_, due_date__lt=today).count(),
    }


# ── список досок ────────────────────────────────────────────────────────

def list_boards(request) -> dict:
    """Что можно открыть (§6.1): своя личная, доски отделов (поддеревья своего
    и управляемых; с «Досками всех отделов» — все, включая неактивные) и
    видимые доски проектов."""
    scope = task_scope.for_request(request)
    try:
        if scope.elevated or scope.all_departments:
            rows = hr.list_departments_brief(limit=5000)
        else:
            rows = [row for row in hr.get_departments_brief(sorted(scope.department_ids))
                    if row.get("is_active")]
    except ServiceDisabled as exc:
        rows = fallback("tasks.board_service.hr_unavailable", [],
                        reason="hr выключен — доски отделов недоступны", expected=True, exc=exc)

    def source(department_id: int) -> str:
        if department_id in scope.managed_subtree:
            return "managed"
        if department_id in scope.department_ids:
            return "own"
        return "all"

    departments = sorted(
        ({"id": row["id"], "name": row["name"], "path": row["path"],
          "depth": row["path"].count("."), "source": source(row["id"]),
          "is_active": bool(row.get("is_active", True))} for row in rows),
        key=lambda row: (not row["is_active"], row["path"]))
    employee_scope, department_ids = project_service.scope_for(request)
    projects = project_service.list_projects(
        employee_scope=employee_scope, department_ids=department_ids,
        refs=board_scope.refs_for_request(request))
    return {
        "personal": True,
        "departments": departments,
        "projects": [{"id": item.id, "name": item.name, "color": item.color,
                      "project_ref": item.project_ref or None} for item in projects],
    }


# ── настройки доски ─────────────────────────────────────────────────────

@transaction.atomic
def save_settings(request, board: Board, data: schemas.BoardSettingsIn) -> dict:
    require_admin(request, board)
    columns = {}
    for status, column in data.columns.items():
        columns[status] = {"title": (column.title or "").strip() or None,
                           "color": column.color, "hidden": column.hidden}
    visible = [status for status in COLUMN_ORDER
               if not (columns.get(status) or {}).get("hidden")]
    if not visible:
        raise DomainError("board_columns_hidden", "Хотя бы одна колонка должна быть видна",
                          status=422)
    BoardSettings.objects.update_or_create(
        board_kind=board.kind, board_id=board.id,
        defaults={"columns": columns, "updated_by": request.token.user_id})
    return {"columns": columns_settings(board)}
