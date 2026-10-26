"""Чек-листы задачи (решение K-20, мастер-план канбана §3.6, §6.3).

Права — как у статуса: отметить, добавить, переименовать и переставить пункт
или чек-лист — ``require_soft_edit``; удалить чек-лист — ``require_full_edit``.
Задача ищется через ``load_for_action``: чек-лист чужой задачи отвечает 404,
а не 403. Порядок — дробные ранги ``board_rank`` под блокировкой строки задачи
(две вставки в один чек-лист не получат один ранг). Каждое действие, кроме
перестановки, — строка журнала задачи. Ответ — чек-лист целиком: фронт
заменяет его в карточке без перечитывания.
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
    existing = list(TaskChecklist.objects.filter(task=task))
    if len(existing) >= CHECKLIST_LIMIT:
        raise DomainError("checklist_limit",
                          f"У задачи не больше {CHECKLIST_LIMIT} чек-листов", status=422)
    items = []
    if template is not None:
        items = board_fields.template_for(task, template.board_kind, template.board_id,
                                          template.template_id)["items"]
    checklist = TaskChecklist.objects.create(
        task=task, title=title, position=_position(existing, None, None, None, "чек-листы"),
        created_by_id=_actor(request))
    if items:
        TaskChecklistItem.objects.bulk_create([
            TaskChecklistItem(checklist=checklist, text=text, position=rank,
                              created_by_id=_actor(request))
            for text, rank in zip(items, board_rank.spread(len(items)))])
    task_service._log(task, _actor(request), "checklist_added", None, title)
    return _one(checklist)


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
    items = list(checklist.items.all())
    if len(items) >= ITEM_LIMIT:
        raise DomainError("checklist_limit",
                          f"В чек-листе не больше {ITEM_LIMIT} пунктов", status=422)
    item = TaskChecklistItem.objects.create(
        checklist=checklist, text=text,
        position=_position(items, None, before_id, after_id, "чек-лист"),
        created_by_id=_actor(request))
    task_service._log(task, _actor(request), "checklist_item_added", None, text)
    if board_rank.needs_rebalance(item.position):
        _respread(list(checklist.items.all()))
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
    if is_done is not None and is_done != item.is_done:
        item.is_done = is_done
        item.done_by_id = actor if is_done else None
        item.done_at = timezone.now() if is_done else None
        task_service._log(task, actor,
                          "checklist_item_checked" if is_done else "checklist_item_unchecked",
                          None, item.text)
    if move:
        item.position = _position(list(target.items.all()), item.id, before_id, after_id,
                                  "чек-лист")
        item.checklist = target
    item.save()
    if board_rank.needs_rebalance(item.position):
        _respread(list(target.items.all()))
    return _one(target)


@transaction.atomic
def delete_item(item_id: int, request) -> dict:
    item = _item(item_id)
    task = _lock_task(item.checklist.task_id, request)
    checklist = item.checklist
    task_service._log(task, _actor(request), "checklist_item_deleted", item.text, None)
    item.delete()
    return _one(checklist)
