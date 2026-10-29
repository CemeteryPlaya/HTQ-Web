"""«Рекомендации» автоматизации (решение L-04; спецификация логики
docs/plans/2026-10-28-kanban-automation-logic.md, §15) — как в Trello:
подсказки кнопок на карточке по МОИМ повторяющимся ручным действиям на
домашних задачах доски.

Источник — журнал задачи за ``WINDOW_DAYS`` дней: мои строки без
``via_rule_id`` (правку сделал я, а не автоматизация). Образцы — перенос в
колонку, «присоединиться» (сам стал исполнителем), чек-лист по шаблону
доски, вариант списка или флажок своего поля. Метки журнал задачи не пишет —
подсказок по ним нет. Подсказка появляется от ``THRESHOLD`` повторов, их не
больше ``LIMIT``; образец, который уже закрывает кнопка доски, и скрытые мной
подсказки не показываются. «Добавить» — обычное создание кнопки
администратором доски (``rules.create``), «Скрыть» запоминается за человеком
и доской.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ...models import (AutomationKind, AutomationRule, AutomationSuggestionDismissal,
                       BoardField, BoardFieldType, BoardSettings, Status, TaskActivity)
from .. import board_fields
from .. import board_service
from .. import task_notify
from .. import task_scope
from . import engine
from . import rules

WINDOW_DAYS = 30
THRESHOLD = 10
LIMIT = 3


def _board_parts(board):
    row = BoardSettings.objects.filter(board_kind=board.kind, board_id=board.id).first()
    columns = (row.columns if row is not None else None) or {}
    templates = {item["title"].casefold(): item for item in board_fields.templates_of(row)}
    fields = {field.pk: field for field in BoardField.objects.filter(
        board_kind=board.kind, board_id=board.id)}
    return columns, templates, fields


def _column_title(columns: dict, status: str) -> str:
    return ((columns.get(status) or {}).get("title")
            or task_notify.STATUS_LABELS.get(status, status))


def _field_id(field_name: str) -> int | None:
    raw = field_name[len(board_fields.FIELD_PREFIX):]
    return int(raw) if raw.isdigit() else None


def _proposal(field_name: str, new: str | None, user_id: int, columns, templates, fields):
    """Строка журнала → ``(ключ, название, значок, действия)`` или ``None``."""
    if not new:
        return None
    if field_name == "status":
        if new not in Status.values or (columns.get(new) or {}).get("hidden"):
            return None
        return (f"move:{new}", f"Перенести в «{_column_title(columns, new)}»", "arrow-right",
                [{"type": "move", "status": new, "position": "top"}])
    if field_name == "assignee_id":
        if new != str(user_id):
            return None
        return ("join", "Присоединиться", "user-plus", [{"type": "join_actor"}])
    if field_name == "checklist_added":
        template = templates.get(new.casefold())
        if template is None:
            return None
        return (f"checklist:{template['id']}", f"Чек-лист «{template['title']}»", "list-checks",
                [{"type": "add_checklist", "title": template["title"],
                  "template_id": template["id"]}])
    field = fields.get(_field_id(field_name))
    if field is None:
        return None
    if field.field_type == BoardFieldType.CHECKBOX and new == "true":
        return (f"field:{field.pk}:true", f"«{field.name}» — отметить", "check",
                [{"type": "set_field", "field_id": field.pk, "value": True}])
    if field.field_type == BoardFieldType.LIST:
        # В журнале — название варианта на момент правки; переименован — мимо.
        option = next((item for item in field.options or [] if item["name"] == new), None)
        if option is None:
            return None
        return (f"field:{field.pk}:{option['id']}", f"«{field.name}»: {option['name']}", "tag",
                [{"type": "set_field", "field_id": field.pk, "value": option["id"]}])
    return None


def _covered(board) -> set[str]:
    """Образцы, которые уже закрывает кнопка на карточке этой доски."""
    keys = set()
    for rule in AutomationRule.objects.filter(board_kind=board.kind, board_id=board.id,
                                              kind=AutomationKind.CARD_BUTTON):
        if len(rule.actions) != 1:
            continue
        action = rule.actions[0]
        kind = action.get("type")
        if kind == "move":
            keys.add(f"move:{action.get('status')}")
        elif kind == "join_actor":
            keys.add("join")
        elif kind == "add_checklist" and action.get("template_id"):
            keys.add(f"checklist:{action['template_id']}")
        elif kind == "set_field" and action.get("mode", "value") == "value":
            value = action.get("value")
            keys.add(f"field:{action.get('field_id')}:{'true' if value is True else value}")
    return keys


def for_user(request, board) -> dict:
    """Мои подсказки на этой доске; ``can_add`` — я администратор доски."""
    rules.require_shared(board)
    user_id = task_scope.for_request(request).user_id
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    rows = (TaskActivity.objects
            .filter(task__in=engine.home_tasks(board.kind, board.id), actor_id=user_id,
                    via_rule_id__isnull=True, created_at__gte=since)
            .filter(Q(field_name__in=("status", "assignee_id", "checklist_added"))
                    | Q(field_name__startswith=board_fields.FIELD_PREFIX))
            .values_list("field_name", "new_value", "created_at"))
    columns, templates, fields = _board_parts(board)
    seen: dict[str, dict] = {}
    for field_name, new, at in rows:
        proposal = _proposal(field_name, new, user_id, columns, templates, fields)
        if proposal is None:
            continue
        key, name, icon, actions = proposal
        entry = seen.setdefault(key, {"key": key, "name": name, "icon": icon,
                                      "actions": actions, "count": 0, "last_at": at})
        entry["count"] += 1
        entry["last_at"] = max(entry["last_at"], at)
    skip = _covered(board) | set(AutomationSuggestionDismissal.objects.filter(
        board_kind=board.kind, board_id=board.id, user_id=user_id).values_list("key", flat=True))
    items = sorted((entry for entry in seen.values()
                    if entry["count"] >= THRESHOLD and entry["key"] not in skip),
                   key=lambda entry: (-entry["count"], entry["key"]))[:LIMIT]
    return {"items": items, "can_add": board_service.is_admin(request, board)}


def dismiss(request, board, key: str) -> None:
    """«Скрыть» — больше не показывать мне эту подсказку на этой доске."""
    rules.require_shared(board)
    AutomationSuggestionDismissal.objects.get_or_create(
        board_kind=board.kind, board_id=board.id,
        user_id=task_scope.for_request(request).user_id, key=key[:80])
