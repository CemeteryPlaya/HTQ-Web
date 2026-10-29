"""Чек-листы задачи (решение K-20, мастер-план канбана §3.6, §6.3).

Права — как у статуса: отметить, добавить, переименовать и переставить пункт
или чек-лист — ``require_soft_edit``; удалить чек-лист — ``require_full_edit``.
Задача ищется через ``load_for_action``: чек-лист чужой задачи отвечает 404,
а не 403. Порядок — дробные ранги ``board_rank`` под блокировкой строки задачи
(две вставки в один чек-лист не получат один ранг). Каждое действие, кроме
перестановки, — строка журнала задачи. Ответ — чек-лист целиком: фронт
заменяет его в карточке без перечитывания. Правки без проверки прав
(``add_checklist``, ``add_item_to``, ``set_item_done``, ``remove_item``) зовёт
и автоматизация доски (этап S4); они же отдают её события.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from htqweb.errors import DomainError

from ..models import Task, TaskChecklist, TaskChecklistItem
from . import board_fields
from . import board_rank
from . import hydration
from . import ranked
from . import task_scope
from . import task_service
from .automation import events as automation
from .automation.context import Event

CHECKLIST_LIMIT = 20
ITEM_LIMIT = 200


# ── ответ ───────────────────────────────────────────────────────────────

def _payload(checklist: TaskChecklist, items: list[TaskChecklistItem], users: dict) -> dict:
    done = sum(1 for item in items if item.is_done)
    return {
        "id": checklist.id,
        "title": checklist.title,
        "position": checklist.position,
        "items": [
            {
                "id": item.id,
                "text": item.text,
                "is_done": item.is_done,
                "done_by": ({"id": item.done_by_id,
                             "name": hydration.user_name(users, item.done_by_id)}
                            if item.done_by_id else None),
                "done_at": item.done_at,
                "position": item.position,
            }
            for item in items
        ],
        "done": done,
        "total": len(items),
    }


def payloads(checklists: list[TaskChecklist]) -> list[dict]:
    """Чек-листы с пунктами — имена отметивших одним батчем."""
    by_list = {checklist.id: [] for checklist in checklists}
    for item in (TaskChecklistItem.objects.filter(checklist_id__in=list(by_list))
                 .order_by("position", "id")):
        by_list[item.checklist_id].append(item)
    users = hydration.user_briefs(item.done_by_id for items in by_list.values()
                                  for item in items)
    return [_payload(checklist, by_list[checklist.id], users) for checklist in checklists]


def for_task(task_id: int) -> list[dict]:
    """Чек-листы задачи для карточки (видимость проверил вызывающий)."""
    return payloads(list(TaskChecklist.objects.filter(task_id=task_id)
                         .order_by("position", "id")))


def _one(checklist: TaskChecklist) -> dict:
    return payloads([checklist])[0]


# ── доступ ──────────────────────────────────────────────────────────────

def _lock_task(task_id: int, request, *, full: bool = False) -> Task:
    """Видимость (404), право и блокировка строки задачи. Блокировка —
    отдельным запросом: выборка видимости с ``distinct`` несовместима с
    ``FOR UPDATE`` (как у «Взять в работу»)."""
    task = task_service.load_for_action(task_id, request)
    if full:
        task_service.require_full_edit(task, request)
    else:
        task_service.require_soft_edit(task, request)
    return Task.objects.select_for_update().get(pk=task.pk)


def _checklist(checklist_id: int) -> TaskChecklist:
    checklist = TaskChecklist.objects.filter(pk=checklist_id).first()
    if checklist is None:
        raise Http404("Checklist not found")
    return checklist


def _item(item_id: int) -> TaskChecklistItem:
    item = TaskChecklistItem.objects.select_related("checklist").filter(pk=item_id).first()
    if item is None:
        raise Http404("Checklist item not found")
    return item


def _actor(request) -> int:
    return task_scope.for_request(request).user_id


# ── порядок ─────────────────────────────────────────────────────────────

def _position(rows: list, moving_id: int | None, before_id: int | None,
              after_id: int | None, model_name: str) -> str:
    """Ранг между соседями; сосед не из этого списка — 409, как у карточек
    доски: список изменился, клиент перечитывает."""
    return ranked.position_between(rows, moving_id, before_id, after_id,
                                   code="checklist_order_stale", what=model_name)


_respread = ranked.respread


# ── правка без проверки прав (её зовут ручки ниже и автоматизация, S4) ──
#
# Строку задачи блокирует вызывающий. Каждая правка пишет журнал задачи и
# отдаёт события автоматизации доски.

def _complete(checklist_id: int) -> bool:
    """Чек-лист выполнен: пункты есть, и все отмечены."""
    items = TaskChecklistItem.objects.filter(checklist_id=checklist_id)
    return items.exists() and not items.filter(is_done=False).exists()


def _state_event(task: Task, checklist: TaskChecklist, before: bool, actor: int | None):
    after = _complete(checklist.pk)
    if before == after:
        return None
    return Event("checklist_completed" if after else "checklist_uncompleted", task.pk, actor,
                 {"checklist_id": checklist.pk, "title": checklist.title})


def _item_event(kind: str, task: Task, item: TaskChecklistItem, title: str,
                actor: int | None) -> Event:
    return Event(kind, task.pk, actor, {"item_id": item.pk, "text": item.text,
                                        "checklist_title": title})


def add_checklist(task: Task, title: str, items: list[str], actor: int | None) -> TaskChecklist:
    """Новый чек-лист в конец; пункты — по порядку (копия шаблона)."""
    existing = list(TaskChecklist.objects.filter(task=task))
    if len(existing) >= CHECKLIST_LIMIT:
        raise DomainError("checklist_limit",
                          f"У задачи не больше {CHECKLIST_LIMIT} чек-листов", status=422)
    checklist = TaskChecklist.objects.create(
        task=task, title=title, position=_position(existing, None, None, None, "чек-листы"),
        created_by_id=actor)
    rows = []
    if items:
        rows = TaskChecklistItem.objects.bulk_create([
            TaskChecklistItem(checklist=checklist, text=text, position=rank, created_by_id=actor)
            for text, rank in zip(items[:ITEM_LIMIT], board_rank.spread(len(items[:ITEM_LIMIT])))])
    task_service._log(task, actor, "checklist_added", None, title)
    automation.emit(Event("checklist_added", task.pk, actor,
                          {"checklist_id": checklist.pk, "title": title}),
                    *[_item_event("item_added", task, row, title, actor) for row in rows])
    return checklist


def add_item_to(task: Task, checklist: TaskChecklist, text: str, actor: int | None, *,
                before_id: int | None = None, after_id: int | None = None) -> TaskChecklistItem:
    items = list(checklist.items.all())
    if len(items) >= ITEM_LIMIT:
        raise DomainError("checklist_limit",
                          f"В чек-листе не больше {ITEM_LIMIT} пунктов", status=422)
    was_complete = _complete(checklist.pk)
    item = TaskChecklistItem.objects.create(
        checklist=checklist, text=text,
        position=_position(items, None, before_id, after_id, "чек-лист"), created_by_id=actor)
    task_service._log(task, actor, "checklist_item_added", None, text)
    if board_rank.needs_rebalance(item.position):
        _respread(list(checklist.items.all()))
    automation.emit(_item_event("item_added", task, item, checklist.title, actor),
                    _state_event(task, checklist, was_complete, actor))
    return item


def set_item_done(task: Task, item: TaskChecklistItem, is_done: bool, actor: int | None) -> None:
    """Отметить или снять пункт; события — пункт и смена «выполнен» чек-листа."""
    if item.is_done == is_done:
        return
    checklist = item.checklist
    was_complete = _complete(checklist.pk)
    item.is_done = is_done
    item.done_by_id = actor if is_done else None
    item.done_at = timezone.now() if is_done else None
    item.save(update_fields=["is_done", "done_by_id", "done_at", "updated_at"])
    task_service._log(task, actor,
                      "checklist_item_checked" if is_done else "checklist_item_unchecked",
                      None, item.text)
    automation.emit(_item_event("item_checked" if is_done else "item_unchecked", task, item,
                                checklist.title, actor),
                    _state_event(task, checklist, was_complete, actor))


def remove_item(task: Task, item: TaskChecklistItem, actor: int | None) -> None:
    checklist = item.checklist
    was_complete = _complete(checklist.pk)
    task_service._log(task, actor, "checklist_item_deleted", item.text, None)
    item.delete()
    automation.emit(_state_event(task, checklist, was_complete, actor))


# ── чек-листы ───────────────────────────────────────────────────────────

def list_checklists(task_id: int, request) -> list[dict]:
    task_service.load_for_action(task_id, request)
    return for_task(task_id)


@transaction.atomic
def create_checklist(task_id: int, request, title: str, template=None) -> dict:
    """``template`` — ``schemas.ChecklistTemplateRef``: пункты копируются из
    шаблона домашней доски задачи (этап S3); журнал — одна строка
    ``checklist_added``, как у пустого чек-листа."""
    task = _lock_task(task_id, request)
    items = []
    if template is not None:
        items = board_fields.template_for(task, template.board_kind, template.board_id,
                                          template.template_id)["items"]
    return _one(add_checklist(task, title, items, _actor(request)))


@transaction.atomic
def update_checklist(checklist_id: int, request, *, title: str | None = None,
                     move: bool = False, before_id: int | None = None,
                     after_id: int | None = None) -> dict:
    checklist = _checklist(checklist_id)
    task = _lock_task(checklist.task_id, request)
    checklist = TaskChecklist.objects.get(pk=checklist.pk)
    if title is not None and title != checklist.title:
        task_service._log(task, _actor(request), "checklist_renamed", checklist.title, title)
        checklist.title = title
    if move:
        siblings = list(TaskChecklist.objects.filter(task=task))
        checklist.position = _position(siblings, checklist.id, before_id, after_id, "чек-листы")
    checklist.save()
    if board_rank.needs_rebalance(checklist.position):
        _respread(list(TaskChecklist.objects.filter(task=task)))
        checklist.refresh_from_db()
    return _one(checklist)


@transaction.atomic
def delete_checklist(checklist_id: int, request) -> None:
    checklist = _checklist(checklist_id)
    task = _lock_task(checklist.task_id, request, full=True)
    task_service._log(task, _actor(request), "checklist_deleted", checklist.title, None)
    checklist.delete()


# ── пункты ──────────────────────────────────────────────────────────────

@transaction.atomic
def add_item(checklist_id: int, request, *, text: str, before_id: int | None = None,
             after_id: int | None = None) -> dict:
    checklist = _checklist(checklist_id)
    task = _lock_task(checklist.task_id, request)
    add_item_to(task, checklist, text, _actor(request), before_id=before_id, after_id=after_id)
    return _one(checklist)


@transaction.atomic
def update_item(item_id: int, request, *, text: str | None = None,
                is_done: bool | None = None, checklist_id: int | None = None,
                move: bool = False, before_id: int | None = None,
                after_id: int | None = None) -> dict:
    item = _item(item_id)
    task = _lock_task(item.checklist.task_id, request)
    item = TaskChecklistItem.objects.select_related("checklist").get(pk=item.pk)
    actor = _actor(request)
    target = item.checklist
    if checklist_id is not None and checklist_id != item.checklist_id:
        # Пункт переезжает только в чек-лист той же задачи; чужой — 404.
        target = TaskChecklist.objects.filter(pk=checklist_id, task=task).first()
        if target is None:
            raise Http404("Checklist not found")
        if target.items.count() >= ITEM_LIMIT:
            raise DomainError("checklist_limit",
                              f"В чек-листе не больше {ITEM_LIMIT} пунктов", status=422)
        move = True
    if text is not None and text != item.text:
        task_service._log(task, actor, "checklist_item_renamed", item.text, text)
        item.text = text
    source = item.checklist
    source_was, target_was = _complete(source.pk), _complete(target.pk)
    if move:
        item.position = _position(list(target.items.all()), item.id, before_id, after_id,
                                  "чек-лист")
        item.checklist = target
    item.save()
    if board_rank.needs_rebalance(item.position):
        _respread(list(target.items.all()))
    if source.pk != target.pk:
        # Пункт ушёл в другой чек-лист — выполненность обоих могла смениться.
        automation.emit(_state_event(task, source, source_was, actor),
                        _state_event(task, target, target_was, actor))
    if is_done is not None:
        set_item_done(task, item, is_done, actor)
    return _one(target)


@transaction.atomic
def delete_item(item_id: int, request) -> dict:
    item = _item(item_id)
    task = _lock_task(item.checklist.task_id, request)
    checklist = item.checklist
    remove_item(task, item, _actor(request))
    return _one(checklist)
