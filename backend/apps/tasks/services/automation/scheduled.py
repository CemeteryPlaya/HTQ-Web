"""Команды по сроку и по расписанию, уборка журнала (этап S4; Celery —
``apps/tasks/tasks.py``, диспетчеры веером по компаниям).

- **По сроку:** «за N дней до срока», «в день срока», «через N дней после» —
  у задач, чья домашняя доска — доска команды. Срабатывает один раз на тройку
  «команда + задача + срок» (``AutomationDueMark``; перенесли срок — снова) и
  не задним числом: только в день, когда наступило (разбор Trello §3.7).
- **По расписанию:** время следующего запуска — у команды (``next_run_at``),
  по Алматы. Действия — над карточками колонки доски (с условиями) или уровня
  доски. Пропущенные запуски (воркер стоял) не догоняются: команда
  выполняется один раз и планирует следующий.
- **Журнал запусков** хранится 90 дней.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from ...models import (TERMINAL_STATUSES, AutomationDueMark, AutomationKind, AutomationRule,
                       AutomationRun, BoardKind, Task)
from .. import board_service
from . import context
from . import engine
from .context import Event

logger = logging.getLogger(__name__)

RUN_RETENTION_DAYS = 90
#: Карточек за один запуск команды над колонкой — как у колонки доски.
CARDS_PER_RUN = 200


# ── расписание ──────────────────────────────────────────────────────────

def _fits(trigger: dict, day) -> bool:
    freq = trigger.get("freq")
    if freq == "daily":
        return True
    if freq == "weekdays":
        return day.isoweekday() <= 5
    if freq == "weekly":
        return day.isoweekday() in set(trigger.get("weekdays") or [])
    if freq == "monthly":
        return day.day == trigger.get("day_of_month")
    return False


def next_run(trigger: dict, after: datetime | None = None) -> datetime | None:
    """Ближайший запуск строго после ``after`` (по умолчанию — сейчас)."""
    after = (after or timezone.now()).astimezone(context.LOCAL_TZ)
    hour, minute = (int(part) for part in (trigger.get("time") or "09:00").split(":"))
    day = after.date()
    for _ in range(400):
        moment = datetime.combine(day, time(hour, minute), tzinfo=context.LOCAL_TZ)
        if moment > after and _fits(trigger, day):
            return moment
        day += timedelta(days=1)
    return None


def _home_tasks(rule: AutomationRule):
    """Задачи, чья домашняя доска — доска автоматизации (K-35)."""
    rows = Task.objects.filter(is_deleted=False)
    if rule.board_kind == BoardKind.DEPARTMENT:
        return rows.filter(department_id=rule.board_id)
    return rows.filter(project_id=rule.board_id)


def run_cards(rule: AutomationRule, tasks, *, actor_id: int | None, event_type: str) -> int:
    """Действия автоматизации над карточками — у каждой своя цепочка: пределы
    цепочки считаются на карточку, а не на всю колонку."""
    done = 0
    for task in tasks:
        with context.chain(actor_id) as (chain, _fresh):
            event = Event(event_type, task.pk, actor_id, by_automation=actor_id is None)
            status = engine.execute(chain, rule, task, event, actor_id=actor_id,
                                    event_name=event_type)
            engine.drain(chain)
        done += status == "ok"
    return done


def run_board(rule: AutomationRule, *, actor_id: int | None, event_type: str) -> str:
    with context.chain(actor_id) as (chain, _fresh):
        event = Event(event_type, 0, actor_id, by_automation=actor_id is None)
        status = engine.execute_board(chain, rule, event, actor_id=actor_id,
                                      event_name=event_type)
        engine.drain(chain)
    return status


def column_tasks(rule: AutomationRule, board, scope=None):
    status = (rule.trigger.get("cards") or {}).get("status")
    rows = board_service.board_tasks(board, scope)
    if status:
        rows = rows.filter(status=status)
    return list(rows.order_by("pk")[:CARDS_PER_RUN])


def run_schedules() -> int:
    """Команды по расписанию, чьё время пришло (компания — из контекста)."""
    now = timezone.now()
    ran = 0
    rules = AutomationRule.objects.filter(kind=AutomationKind.SCHEDULE, enabled=True)
    for rule in rules:
        if rule.next_run_at is None:
            rule.next_run_at = next_run(rule.trigger, now)
            rule.save(update_fields=["next_run_at", "updated_at"])
            continue
        if rule.next_run_at > now:
            continue
        # Следующий запуск — до исполнения: сбой команды не крутит её по кругу.
        rule.next_run_at = next_run(rule.trigger, now)
        rule.save(update_fields=["next_run_at", "updated_at"])
        try:
            if rule.trigger.get("cards") is None:
                run_board(rule, actor_id=None, event_type="schedule")
            else:
                board = board_service.board_for(rule.board_kind, rule.board_id)
                run_cards(rule, column_tasks(rule, board), actor_id=None, event_type="schedule")
            ran += 1
        except Exception:  # noqa: BLE001 — одна команда не останавливает остальные
            logger.exception("tasks: scheduled automation %s failed", rule.pk)
    return ran


# ── по сроку ────────────────────────────────────────────────────────────

def _due_candidates(rule: AutomationRule, today):
    offset = int(rule.trigger.get("offset_days") or 0)
    working = bool(rule.trigger.get("working"))
    rows = _home_tasks(rule).filter(due_date__isnull=False)
    if not working:
        return list(rows.filter(due_date=today - timedelta(days=offset)))
    # Рабочие дни: окно с запасом на выходные и праздники, точнее — ниже.
    spread = abs(offset) * 2 + 14
    window = list(rows.filter(due_date__gte=today - timedelta(days=spread + max(offset, 0)),
                              due_date__lte=today + timedelta(days=spread + max(-offset, 0))))
    from .actions import _add_days

    return [task for task in window if _add_days(task.due_date, offset, True) == today]


def run_due() -> int:
    """Команды по сроку на сегодня (по Алматы); каждая — один раз на
    «задачу + срок»."""
    today = context.today()
    fired = 0
    for rule in AutomationRule.objects.filter(kind=AutomationKind.DUE, enabled=True):
        try:
            candidates = _due_candidates(rule, today)
        except Exception:  # noqa: BLE001
            logger.exception("tasks: due automation %s: candidates failed", rule.pk)
            continue
        marked = set(AutomationDueMark.objects.filter(
            rule=rule, task__in=candidates).values_list("task_id", "due_date"))
        for task in candidates:
            if (task.pk, task.due_date) in marked:
                continue
            with transaction.atomic():
                # Отметка — первой: повторный запуск в тот же день её увидит.
                _mark, created = AutomationDueMark.objects.get_or_create(
                    rule=rule, task=task, due_date=task.due_date)
            if not created:
                continue
            fired += run_cards(rule, [task], actor_id=None, event_type="due")
    return fired


# ── уборка ──────────────────────────────────────────────────────────────

def purge_runs() -> int:
    cutoff = timezone.now() - timedelta(days=RUN_RETENTION_DAYS)
    deleted, _ = AutomationRun.objects.filter(created_at__lt=cutoff).delete()
    marks, _ = AutomationDueMark.objects.filter(
        created_at__lt=cutoff, task__status__in=list(TERMINAL_STATUSES)).delete()
    return deleted + marks
