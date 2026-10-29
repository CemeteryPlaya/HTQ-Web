"""Движок автоматизации (K-37): событие → правила домашних досок задачи →
триггер → условия → действия, журнал запусков.

Правила — домашних досок задачи (отдел ``department_id``, проект
``project_id``; сначала отдела, потом проекта, внутри — по порядку). Каждое
правило — под своей точкой сохранения: сбой откатывает его целиком и пишется
в журнал, правка человека и соседние правила не страдают. Пределы цепочки —
``context``: упёрлись — правило не выполняется, в журнале ``limited``.
Проверка без совпадения условий — ``no_match``: по ней администратор доски
видит, почему правило не сработало (как «Журналы» Trello); пишется раз на
правило и задачу за цепочку. Предел проверяется после условий: «упёрлось»
пишется, только если правило сработало бы. Ссылка на удалённое — поломка
автоматизации (``refs``), а не молчаливое «да» или «нет» (спецификация
логики, docs/plans/2026-10-28-kanban-automation-logic.md).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q

from htqweb import date_rules
from htqweb.errors import DomainError

from ...models import (TERMINAL_STATUSES, AutomationKind, AutomationRule, AutomationRun,
                       AutomationRunStatus, BoardField, BoardFieldType, BoardKind, Label,
                       Status, Task, TaskAssignee, TaskChecklist, TaskChecklistItem,
                       TaskFieldValue)
from .. import board_fields
from . import context
from . import refs
from .context import Chain, ChainLimit, Event

logger = logging.getLogger(__name__)


# ── правила задачи ──────────────────────────────────────────────────────

def _keys_q(keys) -> Q:
    condition = Q(pk__in=[])
    for kind, board_id in keys:
        condition |= Q(board_kind=kind, board_id=board_id)
    return condition


def rules_of(keys, kinds=(AutomationKind.RULE,)) -> list[AutomationRule]:
    """Включённые автоматизации досок ``keys`` — в порядке досок и правил."""
    keys = list(keys)
    if not keys:
        return []
    rows = list(AutomationRule.objects.filter(_keys_q(keys), kind__in=list(kinds), enabled=True)
                .order_by("position", "id"))
    order = {key: index for index, key in enumerate(keys)}
    return sorted(rows, key=lambda rule: order[(rule.board_kind, rule.board_id)])


def _task_rules(chain: Chain | None, task: Task) -> list[AutomationRule]:
    keys = tuple(board_fields.home_board_keys(task))
    if chain is None:
        return rules_of(keys)
    if keys not in chain.rules_cache:
        chain.rules_cache[keys] = rules_of(keys)
    return chain.rules_cache[keys]


def is_block_rule(rule: AutomationRule) -> bool:
    return any(action.get("type") == "block" for action in rule.actions)


# ── триггер ─────────────────────────────────────────────────────────────

def _same(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def _decimal(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None


def _filled(value) -> bool:
    return value is not None and value is not False and value != ""


def _equal_values(field_type: str, left, right) -> bool:
    if left is None or right is None:
        return False
    if field_type == BoardFieldType.NUMBER:
        return _decimal(left) == _decimal(right)
    if field_type == BoardFieldType.TEXT:
        return _same(str(left), str(right))
    return str(left) == str(right)


def _compare(op: str, value, threshold) -> bool:
    left, right = _decimal(value), _decimal(threshold)
    if left is None or right is None:
        return False
    return left > right if op == "gt" else left < right


def home_tasks(board_kind: str, board_id: int):
    """Домашние задачи доски — только их касается её автоматизация
    (спецификация §2): отдела — с ``department_id`` отдела, проекта — с
    ``project_id`` проекта; подотделы и связанные отделы не входят."""
    rows = Task.objects.filter(is_deleted=False)
    if board_kind == BoardKind.DEPARTMENT:
        return rows.filter(department_id=board_id)
    return rows.filter(project_id=board_id)


def _column_count(rule: AutomationRule, status: str) -> int:
    return home_tasks(rule.board_kind, rule.board_id).filter(status=status).count()


def _all_fields_filled(task: Task, keys) -> bool:
    fields = list(BoardField.objects.filter(_keys_q(keys)))
    if not fields:
        return False
    values = {row.field_id: row for row in TaskFieldValue.objects.filter(task=task, field__in=fields)}
    return all(_filled(board_fields.value_json(field, values.get(field.pk))) for field in fields)


def trigger_matches(rule: AutomationRule, event: Event, task: Task) -> bool:
    trigger = rule.trigger
    kind = trigger.get("type")
    data = event.data
    if event.type == "card_arrived" and not _for_board(rule, data):
        return False  # «пришла на доску» видят только правила этой доски
    if kind == "card_created":
        how = trigger.get("how") or "created"
        if event.type == "card_created":
            wanted = how in ("created", "any")
        elif event.type == "card_arrived":
            wanted = how in ("arrived", "any")
        else:
            return False
        return wanted and trigger.get("status") in (None, data.get("status"))
    if kind == "column_count":
        return _count_crossed(rule, trigger, event)
    if kind in ("moved", "completed", "uncompleted", "cancelled"):
        if event.type != "moved":
            return False
        source, target = data.get("from"), data.get("to")
        if kind == "moved":
            return (trigger.get("from_status") in (None, source)
                    and trigger.get("to_status") in (None, target))
        if kind == "completed":
            return target == Status.DONE
        if kind == "uncompleted":
            return source == Status.DONE
        return target == Status.CANCELLED
    if kind == "fields_filled":
        # Последнее пустое поле ЭТОЙ доски получило значение.
        return (event.type == "field_changed"
                and (data.get("board_kind"), data.get("board_id")) == (rule.board_kind, rule.board_id)
                and not _filled(data.get("old")) and _filled(data.get("new"))
                and _all_fields_filled(task, [(rule.board_kind, rule.board_id)]))
    if kind != event.type:
        return False
    if kind in ("label_added", "label_removed"):
        return trigger.get("label_id") in (None, data.get("label_id"))
    if kind in ("assignee_added", "assignee_removed"):
        return trigger.get("user_id") in (None, data.get("user_id"))
    if kind in ("checklist_added", "checklist_completed", "checklist_uncompleted"):
        return trigger.get("title") is None or _same(trigger["title"], data.get("title"))
    if kind in ("item_checked", "item_unchecked", "item_added"):
        return ((trigger.get("text") is None or _same(trigger["text"], data.get("text")))
                and (trigger.get("checklist_title") is None
                     or _same(trigger["checklist_title"], data.get("checklist_title"))))
    if kind == "comment_added":
        body = (data.get("body") or "").strip().casefold()
        text = (trigger.get("text") or "").strip().casefold()
        if trigger.get("match") == "starts_with":
            return body.startswith(text)
        if trigger.get("match") == "contains":
            return text in body
        return True
    if kind == "field_changed":
        return data.get("field_id") == trigger["field_id"] and _field_change_matches(trigger, data)
    return True


def _for_board(rule: AutomationRule, data: dict) -> bool:
    return (data.get("board_kind"), data.get("board_id")) == (rule.board_kind, rule.board_id)


def _count_holds(op: str, count: int, wanted: int) -> bool:
    return count == wanted if op == "eq" else count > wanted if op == "gt" else count < wanted


def _count_crossed(rule: AutomationRule, trigger: dict, event: Event) -> bool:
    """«В колонке стало N»: число домашних карточек колонки только что
    перешло порог — карточка вошла в колонку или вышла из неё, и до этого
    условие не выполнялось (спецификация §3)."""
    status, data = trigger["status"], event.data
    if event.type in ("card_created", "card_arrived"):
        entered, left = data.get("status") == status, False
    elif event.type == "moved":
        entered, left = data.get("to") == status, data.get("from") == status
    else:
        return False
    if not (entered or left):
        return False
    op, wanted = trigger.get("op", "eq"), trigger["count"]
    after = _column_count(rule, status)
    before = after - 1 if entered else after + 1
    return _count_holds(op, after, wanted) and not _count_holds(op, before, wanted)


def _field_change_matches(trigger: dict, data: dict) -> bool:
    op, old, new = trigger.get("op", "set"), data.get("old"), data.get("new")
    if op == "set":
        return _filled(new) and new != old
    if op == "cleared":
        return _filled(old) and not _filled(new)
    if op == "checked":
        return new is True and old is not True
    if op == "unchecked":
        return old is True and new is not True
    if op == "equals":
        return _equal_values(data.get("field_type", ""), new, trigger.get("value")) and new != old
    return _compare(op, new, trigger.get("value"))


# ── условия ─────────────────────────────────────────────────────────────

def _assignee_ids(task: Task) -> set[int]:
    ids = set(TaskAssignee.objects.filter(task=task).values_list("user_id", flat=True))
    if task.assignee_id:
        ids.add(task.assignee_id)
    return ids


def _items(task: Task):
    return TaskChecklistItem.objects.filter(checklist__task=task)


def _field_value(task: Task, field_id: int):
    field = BoardField.objects.filter(pk=field_id).first()
    if field is None:
        raise refs.RefMissing("удалено поле из условия")
    row = TaskFieldValue.objects.filter(task=task, field=field).first()
    return field, board_fields.value_json(field, row)


def _condition_holds(condition: dict, task: Task, event: Event, rule: AutomationRule) -> bool:
    kind = condition["type"]
    negate = bool(condition.get("negate"))
    today = context.today()
    if kind == "in_column":
        result = task.status == condition["status"]
    elif kind == "has_label":
        if not Label.objects.filter(pk=condition["label_id"]).exists():
            raise refs.RefMissing("удалена метка из условия")
        result = task.labels.filter(pk=condition["label_id"]).exists()
    elif kind == "assigned":
        people = _assignee_ids(task)
        who = condition.get("who", "anyone")
        if who == "anyone":
            result = bool(people)
        elif who == "nobody":
            result = not people
        elif who == "user":
            result = condition["user_id"] in people
        else:
            result = people == {condition["user_id"]}
    elif kind == "has_due":
        result = task.due_date is not None
    elif kind == "due_window":
        due = task.due_date
        window = condition["window"]
        if due is None:
            result = False
        elif window == "today":
            result = due == today
        elif window == "overdue":
            result = due < today and task.status not in TERMINAL_STATUSES
        elif window == "within_days":
            result = today <= due <= today + timedelta(days=condition["days"])
        elif window == "this_week":
            result = due.isocalendar()[:2] == today.isocalendar()[:2]
        else:
            result = (due.year, due.month) == (today.year, today.month)
    elif kind == "checklists_complete":
        items = _items(task)
        result = items.exists() and not items.filter(is_done=False).exists()
    elif kind == "checklists_incomplete":
        result = _items(task).filter(is_done=False).exists()
    elif kind == "has_checklist":
        result = any(_same(title, condition["title"]) for title in
                     TaskChecklist.objects.filter(task=task).values_list("title", flat=True))
    elif kind in ("title", "description"):
        text = (task.summary if kind == "title" else task.description or "").strip().casefold()
        needle = (condition.get("text") or "").strip().casefold()
        match = condition["match"]
        result = (not text if match == "empty" else text.startswith(needle)
                  if match == "starts_with" else needle in text)
    elif kind == "field":
        field, value = _field_value(task, condition["field_id"])
        op = condition.get("op", "set")
        if op == "set":
            result = _filled(value)
        elif op == "empty":
            result = not _filled(value)
        elif op == "checked":
            result = value is True
        elif op == "unchecked":
            result = value is not True
        elif op == "equals":
            result = _equal_values(field.field_type, value, condition.get("value"))
        else:
            result = _compare(op, value, condition.get("value"))
    elif kind == "fields_filled":
        result = _all_fields_filled(task, [(rule.board_kind, rule.board_id)])
    elif kind == "actor":
        op = condition["op"]
        if op == "automation":
            result = event.by_automation
        elif op == "person":
            result = not event.by_automation and event.actor_id is not None
        elif op == "is":
            result = event.actor_id == condition["user_id"]
        else:
            result = event.actor_id != condition["user_id"]
    else:
        raise DomainError("automation_ref_missing", f"Неизвестное условие «{kind}»", status=422)
    return result != negate


def conditions_hold(rule: AutomationRule, task: Task, event: Event) -> bool:
    return all(_condition_holds(condition, task, event, rule) for condition in rule.conditions)


# ── журнал ──────────────────────────────────────────────────────────────

def log_run(rule: AutomationRule | None, *, status: str, task: Task | None = None,
            event: str = "", actor_id: int | None = None, details: dict | None = None,
            board: tuple[str, int] | None = None) -> None:
    kind, board_id = board or (rule.board_kind, rule.board_id)
    AutomationRun.objects.create(
        rule=rule, board_kind=kind, board_id=board_id,
        rule_name=(rule.name if rule is not None else "")[:200], task=task, event=event[:40],
        status=status, actor_id=actor_id, details=details or {})


def _error_text(exc: Exception) -> str:
    if isinstance(exc, DomainError):
        return exc.message
    if isinstance(exc, (ValueError, date_rules.DatesOutOfOrder)):
        return str(exc)
    return "Внутренняя ошибка правила"


def _expected(exc: Exception) -> bool:
    """Сбой по данным, а не по коду: трассировка в лог не нужна."""
    return isinstance(exc, (DomainError, ValueError, date_rules.DatesOutOfOrder))


# ── исполнение ──────────────────────────────────────────────────────────

def _limit_reason(chain: Chain, rule: AutomationRule, event: Event) -> str | None:
    if event.depth > context.MAX_DEPTH:
        return f"глубина цепочки больше {context.MAX_DEPTH}"
    if chain.actions + len(rule.actions) > context.MAX_ACTIONS:
        return f"больше {context.MAX_ACTIONS} действий за цепочку"
    return None


def _failed(chain: Chain, rule: AutomationRule, task: Task | None, event: Event,
            event_name: str, exc: Exception) -> str:
    """Сбой правила — в журнал; ссылка на удалённое ломает автоматизацию."""
    text = _error_text(exc)
    if isinstance(exc, refs.RefMissing):
        refs.mark_broken(rule, text)
        text = f"Автоматизация выключена: {text}"
    elif not _expected(exc):
        logger.exception("tasks: automation %s failed on task %s", rule.pk,
                         task.pk if task is not None else None)
    chain.last_error = text
    log_run(rule, status=AutomationRunStatus.FAILED, task=task, event=event_name,
            actor_id=event.actor_id, details={"error": text})
    return AutomationRunStatus.FAILED


def _run_actions(chain: Chain, rule: AutomationRule, task: Task | None, event: Event,
                 actor_id: int | None):
    """Действия под точкой сохранения: ``(итоги, порождённые события)``."""
    from . import actions

    with transaction.atomic():
        with context.run_as(chain, rule.pk, actor_id=actor_id, event_actor_id=event.actor_id,
                            depth=event.depth) as now:
            results = actions.run_all(rule, task, event, now)
            return results, list(now.produced)


def execute(chain: Chain, rule: AutomationRule, task: Task, event: Event, *,
            actor_id: int | None, check: bool = True, event_name: str = "") -> str:
    """Проверить условия и выполнить действия правила под точкой сохранения.
    Возвращает итог журнала; события правок правила встают в очередь, ошибка
    запуска — в ``chain.last_error``."""
    event_name = event_name or event.type
    chain.last_error = None
    if (rule.pk, task.pk) in chain.executed:
        return "skipped"
    try:
        with transaction.atomic():
            matched = not check or conditions_hold(rule, task, event)
    except Exception as exc:  # noqa: BLE001 — условие упало — сбой правила, не правки
        return _failed(chain, rule, task, event, event_name, exc)
    if not matched:
        if (rule.pk, task.pk) not in chain.no_match:
            chain.no_match.add((rule.pk, task.pk))
            log_run(rule, status=AutomationRunStatus.NO_MATCH, task=task, event=event_name,
                    actor_id=event.actor_id)
        return AutomationRunStatus.NO_MATCH
    if reason := _limit_reason(chain, rule, event):
        log_run(rule, status=AutomationRunStatus.LIMITED, task=task, event=event_name,
                actor_id=event.actor_id, details={"reason": reason})
        return AutomationRunStatus.LIMITED
    try:
        results, produced = _run_actions(chain, rule, task, event, actor_id)
    except ChainLimit as exc:
        log_run(rule, status=AutomationRunStatus.LIMITED, task=task, event=event_name,
                actor_id=event.actor_id, details={"reason": str(exc)})
        return AutomationRunStatus.LIMITED
    except Exception as exc:  # noqa: BLE001 — сбой правила откатывает только его
        return _failed(chain, rule, task, event, event_name, exc)
    chain.executed.add((rule.pk, task.pk))
    chain.actions += len(rule.actions)
    log_run(rule, status=AutomationRunStatus.OK, task=task, event=event_name,
            actor_id=event.actor_id, details={"actions": results})
    chain.queue.extend(produced)
    return AutomationRunStatus.OK


def execute_board(chain: Chain, rule: AutomationRule, event: Event, *,
                  actor_id: int | None, event_name: str) -> str:
    """Действия уровня доски (кнопка доски, расписание без карточек)."""
    chain.last_error = None
    try:
        results, produced = _run_actions(chain, rule, None, event, actor_id)
    except ChainLimit as exc:
        log_run(rule, status=AutomationRunStatus.LIMITED, event=event_name,
                actor_id=event.actor_id, details={"reason": str(exc)})
        return AutomationRunStatus.LIMITED
    except Exception as exc:  # noqa: BLE001 — сбой автоматизации откатывает только её
        return _failed(chain, rule, None, event, event_name, exc)
    chain.actions += len(rule.actions)
    log_run(rule, status=AutomationRunStatus.OK, event=event_name, actor_id=event.actor_id,
            details={"actions": results})
    chain.queue.extend(produced)
    return AutomationRunStatus.OK


def _matches(chain: Chain, rule: AutomationRule, event: Event, task: Task) -> bool:
    """Триггер — под точкой сохранения: сбой проверки (подсчёт колонки, поля
    доски) — сбой правила в журнале, а не правки человека."""
    try:
        with transaction.atomic():
            return trigger_matches(rule, event, task)
    except Exception as exc:  # noqa: BLE001
        _failed(chain, rule, task, event, event.type, exc)
        return False


def drain(chain: Chain) -> None:
    """Обработать очередь событий цепочки до конца."""
    while chain.queue:
        event = chain.queue.popleft()
        task = Task.objects.filter(pk=event.task_id, is_deleted=False).first()
        if task is None:
            continue
        for rule in _task_rules(chain, task):
            if not rule.enabled or is_block_rule(rule):
                continue  # сломанную в этой же цепочке выключили
            if not _matches(chain, rule, event, task):
                continue
            # Предыдущее правило могло изменить задачу — условия по свежей строке.
            task.refresh_from_db()
            execute(chain, rule, task, event, actor_id=None)


# ── запрет ручного переноса ─────────────────────────────────────────────

def blocking_rule(task: Task, event: Event) -> AutomationRule | None:
    """Запрет, который держит этот ручной перенос. Запрет со ссылкой на
    удалённое ломается (уведомление администраторам), а не молча пропускает."""
    for rule in _task_rules(None, task):
        if not is_block_rule(rule) or not trigger_matches(rule, event, task):
            continue
        try:
            with transaction.atomic():
                holds = conditions_hold(rule, task, event)
        except refs.RefMissing as exc:
            refs.mark_broken(rule, exc.message)
            continue
        except DomainError:
            continue
        if holds:
            return rule
    return None


def record_blocked(blocked) -> None:
    """Запрет — в журнал запусков (правка уже откатилась)."""
    task = Task.objects.filter(pk=blocked.task_id).first()
    rule = AutomationRule.objects.filter(pk=blocked.rule.pk).first()
    if rule is None:
        return
    log_run(rule, status=AutomationRunStatus.BLOCKED, task=task, event="moved",
            actor_id=blocked.actor_id,
            details={"from": blocked.event.data.get("from"), "to": blocked.event.data.get("to"),
                     "message": blocked.message})
