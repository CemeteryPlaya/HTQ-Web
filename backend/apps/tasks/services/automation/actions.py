"""Действия автоматизации поверх сервисов задач (этап S4; каталог — ``catalog``).

Действия идут по порядку; сбой любого — сбой правила: движок откатывает его
целиком. Права не проверяются (K-39): сервисы зовутся внутренним путём
(``scope=None``) от имени актора исполнения — у правила «Автоматизация»
(``None``), у кнопки — нажавший. Их правки отдают события сами — цепочку
продолжает движок. Действия уровня доски (кнопка доски и расписание без
карточек) работают без задачи: создать задачу, сортировать колонку,
уведомить.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from ... import schemas
from ...models import (TRANSITIONS, BoardField, BoardFieldType, BoardKind, BoardSettings, Label,
                       Priority, Task, TaskAssignee, TaskChecklist, TaskChecklistItem,
                       TaskFieldValue)
from .. import board_fields
from .. import board_service
from .. import checklist_service
from .. import hydration
from .. import task_content_service
from .. import task_notify
from .. import task_service
from . import context
from .context import Running


class ActionError(DomainError):
    def __init__(self, message: str):
        super().__init__("automation_action_failed", message, status=422)


class _Ctx:
    def __init__(self, rule, task: Task | None, event, now: Running | None):
        self.rule = rule
        self.task = task
        self.event = event
        # Кто действует (журнал, уведомления) и кто сделал событие.
        self.actor = now.actor_id if now is not None else None
        self.event_actor = event.actor_id if event is not None else None
        self.board = board_service.board_for(rule.board_kind, rule.board_id)

    def fresh(self) -> Task:
        self.task.refresh_from_db()
        return self.task


# ── общее ───────────────────────────────────────────────────────────────

def _status_label(status: str) -> str:
    return task_notify.STATUS_LABELS.get(status, status)


def render(ctx: _Ctx, template: str) -> str:
    """Переменные: ``{cardname}``, ``{username}``, ``{date}``, ``{duedate}``."""
    task = ctx.task
    who = ctx.event_actor
    name = (hydration.user_name(hydration.user_briefs([who]), who) if who else None) \
        or "Автоматизация"
    due = task.due_date.strftime("%d.%m.%Y") if task is not None and task.due_date else ""
    return (template.replace("{cardname}", task.summary if task is not None else "")
            .replace("{username}", name)
            .replace("{date}", context.today().strftime("%d.%m.%Y"))
            .replace("{duedate}", due)).strip()


def _update(ctx: _Ctx, **changes) -> None:
    task_service.update_task(ctx.task.pk, schemas.TaskUpdate(**changes), user_id=ctx.actor,
                             scope=None)
    ctx.fresh()


def _set_status(ctx: _Ctx, target: str) -> bool:
    task = ctx.fresh()
    if task.status == target:
        return False
    if target not in TRANSITIONS.get(task.status, frozenset()):
        raise ActionError(f"Из колонки «{_status_label(task.status)}» в «{_status_label(target)}» "
                          "перенести нельзя")
    _update(ctx, status=target)
    return True


def _add_days(start: date, days: int, working: bool) -> date:
    """Через ``days`` дней (рабочих — по производственному календарю РК)."""
    if not working:
        return start + timedelta(days=days)
    step = 1 if days >= 0 else -1
    current, left = start, abs(days)
    while left:
        current += timedelta(days=step)
        if refdata.is_working_day(current):
            left -= 1
    return current


def _field(ctx: _Ctx, field_id: int) -> BoardField:
    field = BoardField.objects.filter(pk=field_id).first()
    if field is None:
        raise ActionError("Поля из правила больше нет")
    if (field.board_kind, field.board_id) not in board_fields.home_board_keys(ctx.task):
        raise ActionError(f"Поле «{field.name}» не с доски этой задачи")
    return field


def _field_value(ctx: _Ctx, field: BoardField):
    row = TaskFieldValue.objects.filter(task=ctx.task, field=field).first()
    return board_fields.value_json(field, row)


def _store(ctx: _Ctx, field: BoardField, raw) -> None:
    value = board_fields.parse_value(field, raw)
    board_fields.store_value(ctx.task, field, value, ctx.actor)


# ── перемещение ─────────────────────────────────────────────────────────

def _move(ctx: _Ctx, action: dict) -> dict:
    _set_status(ctx, action["status"])
    board_service.place(ctx.board, ctx.fresh(), action.get("position", "bottom"))
    return {"to": action["status"]}


def _reposition(ctx: _Ctx, action: dict) -> dict:
    board_service.place(ctx.board, ctx.fresh(), action.get("position", "top"))
    return {}


def _cancel(ctx: _Ctx, action: dict) -> dict:
    _set_status(ctx, "cancelled")
    return {}


def _complete(ctx: _Ctx, action: dict) -> dict:
    _set_status(ctx, "done")
    return {}


# ── метки ───────────────────────────────────────────────────────────────

def _labels(ctx: _Ctx) -> set[int]:
    return set(ctx.task.labels.values_list("pk", flat=True))


def _add_label(ctx: _Ctx, action: dict) -> dict:
    if not Label.objects.filter(pk=action["label_id"]).exists():
        raise ActionError("Метки из правила больше нет")
    labels = _labels(ctx)
    if action["label_id"] not in labels:
        _update(ctx, label_ids=sorted(labels | {action["label_id"]}))
    return {}


def _remove_label(ctx: _Ctx, action: dict) -> dict:
    labels = _labels(ctx)
    if action["label_id"] in labels:
        _update(ctx, label_ids=sorted(labels - {action["label_id"]}))
    return {}


def _remove_all_labels(ctx: _Ctx, action: dict) -> dict:
    if _labels(ctx):
        _update(ctx, label_ids=[])
    return {}


# ── задачи ──────────────────────────────────────────────────────────────

def _board_home(ctx: _Ctx) -> dict:
    if ctx.rule.board_kind == BoardKind.DEPARTMENT:
        return {"department_id": ctx.rule.board_id}
    return {"project_id": ctx.rule.board_id}


def _create_task(ctx: _Ctx, action: dict) -> dict:
    reporter = ctx.event_actor or ctx.rule.created_by
    created = task_service.create_task(
        schemas.TaskCreate(summary=render(ctx, action["summary"])[:500] or "Задача",
                           status=action.get("status", "todo"), reporter_id=reporter,
                           **_board_home(ctx)),
        user_id=reporter, scope=None)
    board_service.place_new(ctx.board, created)
    return {"task_id": created.pk, "key": created.key}


def _copy_task(ctx: _Ctx, action: dict) -> dict:
    source = ctx.fresh()
    reporter = ctx.event_actor or ctx.rule.created_by
    created = task_service.create_task(
        schemas.TaskCreate(summary=render(ctx, action.get("summary") or "{cardname}")[:500]
                           or source.summary,
                           description=source.description, status=action.get("status", "todo"),
                           reporter_id=reporter, department_id=source.department_id,
                           project_id=source.project_id, priority=source.priority,
                           label_ids=sorted(_labels(ctx))),
        user_id=reporter, scope=None)
    for checklist in TaskChecklist.objects.filter(task=source).order_by("position", "id"):
        items = list(checklist.items.order_by("position", "id").values_list("text", flat=True))
        checklist_service.add_checklist(created, checklist.title, items, ctx.actor)
    board_service.place_new(ctx.board, created)
    return {"task_id": created.pk, "key": created.key}


# ── даты ────────────────────────────────────────────────────────────────

def _set_due(ctx: _Ctx, action: dict) -> dict:
    today = context.today()
    mode = action.get("mode", "in_days")
    if mode == "today":
        due = today
    elif mode == "in_days":
        due = _add_days(today, action.get("days", 0), action.get("working", False))
    else:
        field = _field(ctx, action["field_id"])
        value = _field_value(ctx, field)
        if not value:
            raise ActionError(f"Поле «{field.name}» пустое — срок взять неоткуда")
        due = date.fromisoformat(value)
    _update(ctx, due_date=due)
    return {"due": due.isoformat()}


def _shift_due(ctx: _Ctx, action: dict) -> dict:
    task = ctx.fresh()
    if task.due_date is None:
        raise ActionError("У задачи нет срока — сдвигать нечего")
    due = _add_days(task.due_date, action["days"], action.get("working", False))
    _update(ctx, due_date=due)
    return {"due": due.isoformat()}


def _clear_due(ctx: _Ctx, action: dict) -> dict:
    if ctx.fresh().due_date is not None:
        _update(ctx, due_date=None)
    return {}


def _set_start_today(ctx: _Ctx, action: dict) -> dict:
    _update(ctx, start_date=context.today())
    return {}


def _clear_start(ctx: _Ctx, action: dict) -> dict:
    if ctx.fresh().start_date is not None:
        _update(ctx, start_date=None)
    return {}


# ── чек-листы ───────────────────────────────────────────────────────────

def _same(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def _add_checklist(ctx: _Ctx, action: dict) -> dict:
    items = []
    if action.get("template_id"):
        row = BoardSettings.objects.filter(board_kind=ctx.rule.board_kind,
                                           board_id=ctx.rule.board_id).first()
        template = next((item for item in board_fields.templates_of(row)
                         if item["id"] == action["template_id"]), None)
        if template is None:
            raise ActionError("Шаблона чек-листа из правила больше нет")
        items = template["items"]
    checklist = checklist_service.add_checklist(ctx.task, action["title"], items, ctx.actor)
    return {"checklist_id": checklist.pk}


def _checklists(ctx: _Ctx, title: str | None):
    rows = TaskChecklist.objects.filter(task=ctx.task).order_by("position", "id")
    return [row for row in rows if title is None or _same(row.title, title)]


def _matching_items(ctx: _Ctx, action: dict) -> list[TaskChecklistItem]:
    lists = _checklists(ctx, action.get("checklist_title"))
    return [item for item in TaskChecklistItem.objects.select_related("checklist")
            .filter(checklist__in=lists).order_by("checklist__position", "position", "id")
            if _same(item.text, action["text"])]


def _add_item(ctx: _Ctx, action: dict) -> dict:
    title = action.get("checklist_title")
    lists = _checklists(ctx, title)
    # Чек-листа с таким названием нет — заводится (у Trello без него
    # действие бессмысленно).
    checklist = lists[0] if lists else checklist_service.add_checklist(
        ctx.task, title or "Чек-лист", [], ctx.actor)
    checklist_service.add_item_to(ctx.task, checklist, action["text"], ctx.actor)
    return {}


def _set_items(ctx: _Ctx, items, done: bool) -> dict:
    for item in items:
        checklist_service.set_item_done(ctx.task, item, done, ctx.actor)
    return {"items": len(items)}


def _check_item(ctx: _Ctx, action: dict) -> dict:
    return _set_items(ctx, _matching_items(ctx, action), True)


def _uncheck_item(ctx: _Ctx, action: dict) -> dict:
    return _set_items(ctx, _matching_items(ctx, action), False)


def _all_items(ctx: _Ctx, done: bool) -> list[TaskChecklistItem]:
    return list(TaskChecklistItem.objects.select_related("checklist")
                .filter(checklist__task=ctx.task, is_done=not done)
                .order_by("checklist__position", "position", "id"))


def _check_all(ctx: _Ctx, action: dict) -> dict:
    return _set_items(ctx, _all_items(ctx, True), True)


def _reset_all(ctx: _Ctx, action: dict) -> dict:
    return _set_items(ctx, _all_items(ctx, False), False)


def _remove_item(ctx: _Ctx, action: dict) -> dict:
    items = _matching_items(ctx, action)
    for item in items:
        checklist_service.remove_item(ctx.task, item, ctx.actor)
    return {"items": len(items)}


# ── участники ───────────────────────────────────────────────────────────

def _crew(ctx: _Ctx) -> list[tuple[int, str]]:
    task = ctx.fresh()
    rows = [(row.user_id, row.role) for row in
            TaskAssignee.objects.filter(task=task).order_by("assigned_at", "user_id")]
    if task.assignee_id and all(uid != task.assignee_id for uid, _role in rows):
        rows.insert(0, (task.assignee_id, "primary"))
    return rows


def _replace_crew(ctx: _Ctx, crew: list[tuple[int, str]]) -> None:
    if crew and all(role != "primary" for _uid, role in crew):
        crew = [(crew[0][0], "primary")] + crew[1:]
    task_service.replace_assignees(
        ctx.task.pk, [schemas.AssigneeAssignment(user_id=uid, role=role) for uid, role in crew],
        actor_id=ctx.actor)
    ctx.fresh()


def _add_person(ctx: _Ctx, user_id: int | None) -> dict:
    if not user_id:
        return {"skipped": "нет человека"}
    crew = _crew(ctx)
    if any(uid == user_id for uid, _role in crew):
        return {}
    _replace_crew(ctx, crew + [(user_id, "primary" if not crew else "collaborator")])
    return {"user_id": user_id}


def _join_actor(ctx: _Ctx, action: dict) -> dict:
    return _add_person(ctx, ctx.event_actor)


def _add_assignee(ctx: _Ctx, action: dict) -> dict:
    return _add_person(ctx, action["user_id"])


def _remove_assignee(ctx: _Ctx, action: dict) -> dict:
    crew = _crew(ctx)
    if any(uid == action["user_id"] for uid, _role in crew):
        _replace_crew(ctx, [(uid, role) for uid, role in crew if uid != action["user_id"]])
    return {}


def _remove_all_assignees(ctx: _Ctx, action: dict) -> dict:
    if _crew(ctx):
        _replace_crew(ctx, [])
    return {}


def _random_assignee(ctx: _Ctx, action: dict) -> dict:
    return _add_person(ctx, random.choice(action["user_ids"]))


def _round_robin_assignee(ctx: _Ctx, action: dict) -> dict:
    people = action["user_ids"]
    state = dict(ctx.rule.state or {})
    index = int(state.get("round_robin", -1)) + 1
    state["round_robin"] = index % len(people)
    ctx.rule.state = state
    ctx.rule.save(update_fields=["state", "updated_at"])
    return _add_person(ctx, people[index % len(people)])


def _set_supervisor(ctx: _Ctx, action: dict) -> dict:
    user_id = ctx.event_actor if action.get("who") == "actor" else action.get("user_id")
    if not user_id:
        return {"skipped": "нет человека"}
    task_service.set_supervisor(ctx.task.pk, user_id, ctx.actor)
    return {"user_id": user_id}


def _watch_actor(ctx: _Ctx, action: dict) -> dict:
    if ctx.event_actor:
        task_service.add_watcher(ctx.task.pk, ctx.event_actor)
    return {}


# ── содержимое ──────────────────────────────────────────────────────────

def _rename(ctx: _Ctx, action: dict) -> dict:
    summary = render(ctx, action["summary"])[:500]
    if summary and summary != ctx.fresh().summary:
        _update(ctx, summary=summary)
    return {}


def _set_description(ctx: _Ctx, action: dict) -> dict:
    text = render(ctx, action.get("text", ""))
    current = ctx.fresh().description or ""
    if action.get("mode") == "append" and current:
        text = f"{current}\n\n{text}"
    _update(ctx, description=text[:10000])
    return {}


def _comment(ctx: _Ctx, action: dict) -> dict:
    # Комментарий и так уведомляет участников задачи (K-30): «@card» Trello
    # здесь лишь убирается из текста.
    body = render(ctx, action["text"]).replace("@card", "").strip()
    if not body:
        raise ActionError("Пустой комментарий")
    task_content_service.create_comment(ctx.task.pk, body, author_id=ctx.actor)
    return {}


def _notify(ctx: _Ctx, action: dict) -> dict:
    text = render(ctx, action["text"])
    if ctx.task is not None:
        task_notify.automation_notice(ctx.task, ctx.actor, action["user_ids"], text)
    else:
        task_notify.board_notice(ctx.rule.board_kind, ctx.rule.board_id, ctx.actor,
                                 action["user_ids"], text)
    return {"people": len(action["user_ids"])}


# ── свои поля ───────────────────────────────────────────────────────────

def _set_field(ctx: _Ctx, action: dict) -> dict:
    field = _field(ctx, action["field_id"])
    mode = action.get("mode", "value")
    if mode == "today":
        raw = context.today().isoformat()
    elif mode == "in_days":
        raw = _add_days(context.today(), action.get("days", 0),
                        action.get("working", False)).isoformat()
    elif field.field_type == BoardFieldType.CHECKBOX:
        raw = bool(action.get("value"))
    else:
        raw = action.get("value")
    _store(ctx, field, raw)
    return {}


def _clear_field(ctx: _Ctx, action: dict) -> dict:
    board_fields.store_value(ctx.task, _field(ctx, action["field_id"]), None, ctx.actor)
    return {}


def _increment_field(ctx: _Ctx, action: dict) -> dict:
    field = _field(ctx, action["field_id"])
    try:
        current = Decimal(_field_value(ctx, field) or "0")
        result = current + Decimal(str(action["by"]))
    except InvalidOperation as exc:
        raise ActionError(f"Поле «{field.name}» — не число") from exc
    _store(ctx, field, format(result, "f"))
    return {}


def _shift_field_date(ctx: _Ctx, action: dict) -> dict:
    field = _field(ctx, action["field_id"])
    value = _field_value(ctx, field)
    if not value:
        raise ActionError(f"Поле «{field.name}» пустое — сдвигать нечего")
    _store(ctx, field, _add_days(date.fromisoformat(value), action["days"],
                                 action.get("working", False)).isoformat())
    return {}


# ── сортировка колонки ──────────────────────────────────────────────────

_PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2,
                   Priority.LOW: 3, Priority.TRIVIAL: 4}


def _sort_column(ctx: _Ctx, action: dict) -> dict:
    by = action.get("by", "due")
    reverse = action.get("direction") == "desc"
    if by == "due":
        def key(task):
            return (task.due_date is None, task.due_date or date.max)
    elif by == "priority":
        def key(task):
            return _PRIORITY_ORDER.get(task.priority, 9)
    elif by == "title":
        def key(task):
            return task.summary.casefold()
    elif by == "created":
        def key(task):
            return task.created_at
    else:
        field = BoardField.objects.filter(pk=action["field_id"]).first()
        if field is None:
            raise ActionError("Поля из правила больше нет")

        def key(task):
            row = next((value for value in task.field_values.all()
                        if value.field_id == field.pk), None)
            value = board_fields.value_json(field, row)
            return (value in (None, False, ""), str(value or ""))
    count = board_service.sort_column(ctx.board, action["status"], key, reverse=reverse)
    return {"cards": count}


_HANDLERS = {
    "move": _move, "reposition": _reposition, "cancel": _cancel, "complete": _complete,
    "add_label": _add_label, "remove_label": _remove_label,
    "remove_all_labels": _remove_all_labels,
    "create_task": _create_task, "copy_task": _copy_task,
    "set_due": _set_due, "shift_due": _shift_due, "clear_due": _clear_due,
    "set_start_today": _set_start_today, "clear_start": _clear_start,
    "add_checklist": _add_checklist, "add_item": _add_item, "check_item": _check_item,
    "uncheck_item": _uncheck_item, "check_all": _check_all, "reset_all": _reset_all,
    "remove_item": _remove_item,
    "join_actor": _join_actor, "add_assignee": _add_assignee,
    "remove_assignee": _remove_assignee, "remove_all_assignees": _remove_all_assignees,
    "random_assignee": _random_assignee, "round_robin_assignee": _round_robin_assignee,
    "set_supervisor": _set_supervisor, "watch_actor": _watch_actor,
    "rename": _rename, "set_description": _set_description, "comment": _comment,
    "notify": _notify,
    "set_field": _set_field, "clear_field": _clear_field,
    "increment_field": _increment_field, "shift_field_date": _shift_field_date,
    "sort_column": _sort_column,
}


def run_all(rule, task: Task | None, event, now: Running | None) -> list[dict]:
    """Действия правила по порядку; итог каждого — для журнала запусков."""
    ctx = _Ctx(rule, task, event, now)
    results = []
    for action in rule.actions:
        handler = _HANDLERS.get(action.get("type"))
        if handler is None:
            raise ActionError(f"Неизвестное действие «{action.get('type')}»")
        if task is None and action["type"] not in ("create_task", "sort_column", "notify"):
            raise ActionError("Действие над карточкой — без карточки")
        if task is not None:
            ctx.fresh()
        results.append({"type": action["type"], **(handler(ctx, action) or {})})
    return results
