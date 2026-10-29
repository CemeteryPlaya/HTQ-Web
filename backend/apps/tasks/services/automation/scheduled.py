"""Команды по сроку и по расписанию, уборка журнала (этап S4; Celery —
``apps/tasks/tasks.py``, диспетчеры веером по компаниям).

Спецификация — docs/plans/2026-10-28-kanban-automation-logic.md, §8, §9.

- **По сроку:** «за N дней до срока», «в день срока», «через N дней после» —
  у домашних задач доски команды, кроме выполненных и отменённых.
  Срабатывает один раз на тройку «команда + задача + срок»
  (``AutomationDueMark``; перенесли срок — снова), начиная с ``DUE_HOUR``
  (09:00) по времени платформы: ночью уведомлений нет, и дата доски (UTC) уже
  совпадает с местной. Пропущенные простоем дни догоняются на
  ``DUE_CATCH_UP_DAYS`` назад, но не раньше включения команды
  (``activated_at``): шаблон на доске со старыми просрочками их не помечает.
- **По расписанию:** время следующего запуска — у команды (``next_run_at``),
  по времени платформы; «по рабочим дням» — производственный календарь РК.
  Запуск захватывается условным обновлением ``next_run_at``: два воркера не
  выполнят его дважды. Пропущенный (воркер стоял) выполняется, если ещё тот
  же местный день, иначе — строка журнала «пропущено».
- **Журнал запусков** хранится 90 дней; история настроек (``changed``) — всегда.
"""

from __future__ import annotations

import calendar
import logging
import time as monotonic_clock
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.services import ServiceDisabled
from apps.refdata import interface as refdata
from htqweb.fallback import fallback

from ...models import (TERMINAL_STATUSES, AutomationDueMark, AutomationKind, AutomationRule,
                       AutomationRun, AutomationRunStatus)
from . import catalog
from . import context
from . import engine
from .context import Event

logger = logging.getLogger(__name__)

RUN_RETENTION_DAYS = 90
#: Карточек за один запуск команды над колонкой.
CARDS_PER_RUN = catalog.CARDS_PER_RUN
#: Команды по сроку — не раньше этого часа по времени платформы.
DUE_HOUR = 9
#: На сколько дней назад догоняются пропущенные команды по сроку.
DUE_CATCH_UP_DAYS = 3
#: Бюджет прогона расписаний: меньше жёсткого предела задачи Celery (300 с) —
#: недошедшие команды выполнит следующий прогон через 5 минут.
SCHEDULE_BUDGET_SECONDS = 240


def _due_hour() -> int:
    return int(getattr(settings, "AUTOMATION_DUE_HOUR", DUE_HOUR))


# ── расписание ──────────────────────────────────────────────────────────

def _working_day(day) -> bool:
    """Рабочий день производственного календаря РК; справочники выключены —
    понедельник–пятница."""
    try:
        return refdata.is_working_day(day)
    except ServiceDisabled as exc:
        return fallback("tasks.automation.calendar_unavailable", day.isoweekday() <= 5,
                        reason="справочники выключены — рабочие дни расписания по Пн–Пт",
                        expected=True, exc=exc)


def _fits(trigger: dict, day) -> bool:
    freq = trigger.get("freq")
    if freq == "daily":
        return True
    if freq == "weekdays":
        return _working_day(day)
    if freq == "weekly":
        return day.isoweekday() in set(trigger.get("weekdays") or [])
    if freq == "monthly":
        # 29–31 число в коротком месяце — его последний день.
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(int(trigger.get("day_of_month") or 1), last)
    return False


def next_run(trigger: dict, after: datetime | None = None) -> datetime | None:
    """Ближайший запуск строго после ``after`` (по умолчанию — сейчас)."""
    after = (after or timezone.now()).astimezone(context.local_tz())
    hour, minute = (int(part) for part in (trigger.get("time") or "09:00").split(":"))
    day = after.date()
    for _ in range(400):
        moment = datetime.combine(day, time(hour, minute), tzinfo=context.local_tz())
        if moment > after and _fits(trigger, day):
            return moment
        day += timedelta(days=1)
    return None


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


def run_board(rule: AutomationRule, *, actor_id: int | None, event_type: str) -> tuple[str, str | None]:
    """Действия уровня доски: ``(итог, ошибка запуска)``."""
    with context.chain(actor_id) as (chain, _fresh):
        event = Event(event_type, 0, actor_id, by_automation=actor_id is None)
        status = engine.execute_board(chain, rule, event, actor_id=actor_id,
                                      event_name=event_type)
        error = chain.last_error
        engine.drain(chain)
    return status, error


def column_tasks(rule: AutomationRule):
    """Домашние карточки доски команды в её колонке (спецификация §2), не
    больше ``CARDS_PER_RUN`` — сначала старые."""
    status = (rule.trigger.get("cards") or {}).get("status")
    rows = engine.home_tasks(rule.board_kind, rule.board_id)
    if status:
        rows = rows.filter(status=status)
    return list(rows.order_by("pk")[:CARDS_PER_RUN])


def _claim(rule: AutomationRule, planned, following) -> bool:
    """Захват запуска: ``next_run_at`` сдвигается, только если его ещё никто
    не сдвинул — второй воркер, правка или выключение команды."""
    return bool(AutomationRule.objects.filter(
        pk=rule.pk, enabled=True, next_run_at=planned).update(next_run_at=following))


def run_schedules() -> int:
    """Команды по расписанию, чьё время пришло (компания — из контекста)."""
    now = timezone.now()
    today = now.astimezone(context.local_tz()).date()
    deadline = monotonic_clock.monotonic() + SCHEDULE_BUDGET_SECONDS
    ran = 0
    rules = list(AutomationRule.objects.filter(kind=AutomationKind.SCHEDULE, enabled=True))
    for rule in rules:
        if monotonic_clock.monotonic() > deadline:
            break  # остальные — следующим прогоном
        planned = rule.next_run_at
        if planned is None:
            AutomationRule.objects.filter(pk=rule.pk, next_run_at__isnull=True).update(
                next_run_at=next_run(rule.trigger, now))
            continue
        if planned > now:
            continue
        # Следующий запуск — до исполнения: сбой команды не крутит её по кругу.
        if not _claim(rule, planned, next_run(rule.trigger, now)):
            continue
        if planned.astimezone(context.local_tz()).date() != today:
            engine.log_run(rule, status=AutomationRunStatus.SKIPPED, event="schedule",
                           details={"planned": planned.isoformat()})
            continue
        try:
            if rule.trigger.get("cards") is None:
                run_board(rule, actor_id=None, event_type="schedule")
            else:
                run_cards(rule, column_tasks(rule), actor_id=None, event_type="schedule")
            ran += 1
        except Exception:  # noqa: BLE001 — одна команда не останавливает остальные
            logger.exception("tasks: scheduled automation %s failed", rule.pk)
    return ran


# ── по сроку ────────────────────────────────────────────────────────────

def _due_candidates(rule: AutomationRule, today):
    """Домашние задачи доски, у которых в этот день — «срок ± N дней»; кроме
    выполненных и отменённых (спецификация §8)."""
    offset = int(rule.trigger.get("offset_days") or 0)
    working = bool(rule.trigger.get("working"))
    rows = (engine.home_tasks(rule.board_kind, rule.board_id)
            .filter(due_date__isnull=False).exclude(status__in=list(TERMINAL_STATUSES)))
    if not working:
        return list(rows.filter(due_date=today - timedelta(days=offset)))
    # Рабочие дни: окно с запасом на выходные и праздники, точнее — ниже.
    spread = abs(offset) * 2 + 14
    window = list(rows.filter(due_date__gte=today - timedelta(days=spread + max(offset, 0)),
                              due_date__lte=today + timedelta(days=spread + max(-offset, 0))))
    from .actions import _add_days

    return [task for task in window if _add_days(task.due_date, offset, True) == today]


def _days(rule: AutomationRule, today) -> list:
    """Дни, за которые команда ещё может сработать: сегодня и пропущенные
    простоем, но не раньше её включения."""
    since = (rule.activated_at or rule.created_at).astimezone(context.local_tz()).date()
    first = max(today - timedelta(days=DUE_CATCH_UP_DAYS), since)
    return [first + timedelta(days=step) for step in range((today - first).days + 1)]


def run_due() -> int:
    """Команды по сроку (по времени платформы, с ``DUE_HOUR``); каждая —
    один раз на «задачу + срок»."""
    moment = context.now_local()
    if moment.hour < _due_hour():
        return 0
    today = moment.date()
    fired = 0
    for rule in AutomationRule.objects.filter(kind=AutomationKind.DUE, enabled=True):
        try:
            candidates = list({task.pk: task for day in _days(rule, today)
                               for task in _due_candidates(rule, day)}.values())
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
    """Строки журнала старше 90 дней — кроме истории настроек (``changed``);
    отметки команд по сроку у завершённых задач."""
    cutoff = timezone.now() - timedelta(days=RUN_RETENTION_DAYS)
    deleted, _ = (AutomationRun.objects.filter(created_at__lt=cutoff)
                  .exclude(status=AutomationRunStatus.CHANGED).delete())
    marks, _ = AutomationDueMark.objects.filter(
        created_at__lt=cutoff, task__status__in=list(TERMINAL_STATUSES)).delete()
    return deleted + marks
