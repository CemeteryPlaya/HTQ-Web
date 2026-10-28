"""Команды досок по сроку и по расписанию, уборка журнала (этап S4).

По сроку — один раз на «задачу + срок» и не задним числом; по расписанию —
по времени Алматы, следующий запуск хранится у команды; журнал запусков
живёт 90 дней. Celery-задачи — по компании, диспетчеры — веером.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.tasks import tasks as celery_tasks
from apps.tasks.models import (AutomationDueMark, AutomationKind, AutomationRule, AutomationRun,
                               Status, Task)
from apps.tasks.services.automation import actions, context, scheduled

from .automation_helpers import add_rule, assigned_task, dept_board, label, statuses
from .org_fixtures import EMP_IT, HEAD_IT, make_org, make_task

pytestmark = pytest.mark.django_db

ALMATY = context.LOCAL_TZ


@pytest.fixture
def org():
    return make_org()


def _at(*args) -> datetime:
    return datetime(*args, tzinfo=ALMATY)


# ── расписание ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(("trigger", "after", "expected"), [
    ({"freq": "daily", "time": "09:00"}, _at(2026, 10, 27, 5, 0), _at(2026, 10, 27, 9, 0)),
    ({"freq": "daily", "time": "09:00"}, _at(2026, 10, 27, 9, 0), _at(2026, 10, 28, 9, 0)),
    ({"freq": "weekdays", "time": "08:55"}, _at(2026, 10, 30, 10, 0), _at(2026, 11, 2, 8, 55)),
    ({"freq": "weekly", "weekdays": [3], "time": "18:30"}, _at(2026, 10, 27, 12, 0),
     _at(2026, 10, 28, 18, 30)),
    ({"freq": "monthly", "day_of_month": 31, "time": "07:00"}, _at(2026, 11, 1, 0, 0),
     _at(2026, 12, 31, 7, 0)),
])
def test_next_run_by_almaty_time(trigger, after, expected):
    assert scheduled.next_run({"type": "schedule", **trigger}, after) == expected


def _schedule(org, actions_, cards=None, conditions=None):
    trigger = {"type": "schedule", "freq": "daily", "time": "09:00"}
    if cards is not None:
        trigger["cards"] = cards
    return add_rule(dept_board(org.it), trigger, actions_, conditions,
                    kind=AutomationKind.SCHEDULE, name="По расписанию")


def test_schedule_gets_next_run_on_save_and_runs_when_due(org):
    rule = _schedule(org, [{"type": "create_task", "summary": "Планёрка {date}"}])
    assert rule.next_run_at is not None and rule.next_run_at > timezone.now()
    assert scheduled.run_schedules() == 0                       # время не пришло
    AutomationRule.objects.filter(pk=rule.pk).update(
        next_run_at=timezone.now() - timedelta(minutes=1))
    assert scheduled.run_schedules() == 1
    assert Task.objects.filter(summary__startswith="Планёрка", department_id=org.it.id).count() == 1
    rule.refresh_from_db()
    assert rule.next_run_at > timezone.now()
    assert scheduled.run_schedules() == 0                       # второй раз — не пора


def test_schedule_over_column_cards_with_conditions(org):
    urgent = label("Срочно (расписание)")
    stale = label("Зависла")
    flagged = assigned_task(org.it, EMP_IT)
    flagged.labels.add(urgent)
    plain = assigned_task(org.it, EMP_IT)
    rule = _schedule(org, [{"type": "add_label", "label_id": stale.pk}],
                     cards={"status": "todo"},
                     conditions=[{"type": "has_label", "label_id": urgent.pk}])
    AutomationRule.objects.filter(pk=rule.pk).update(
        next_run_at=timezone.now() - timedelta(minutes=1))
    scheduled.run_schedules()
    assert flagged.labels.filter(pk=stale.pk).exists()
    assert not plain.labels.filter(pk=stale.pk).exists()
    assert sorted(statuses(rule)) == ["no_match", "ok"]


def test_schedule_without_next_run_is_planned_not_run(org):
    rule = _schedule(org, [{"type": "create_task", "summary": "Не сейчас"}])
    AutomationRule.objects.filter(pk=rule.pk).update(next_run_at=None)
    assert scheduled.run_schedules() == 0
    rule.refresh_from_db()
    assert rule.next_run_at is not None
    assert not Task.objects.filter(summary="Не сейчас").exists()


# ── по сроку ────────────────────────────────────────────────────────────

def _due_rule(org, offset, *, working=False, conditions=None, actions_=None):
    return add_rule(dept_board(org.it), {"type": "due", "offset_days": offset, "working": working},
                    actions_ or [{"type": "add_label", "label_id": label("Просрочено (тест)").pk}],
                    conditions, kind=AutomationKind.DUE, name="По сроку")


def test_due_fires_once_per_task_and_due_date(org):
    today = context.today()
    rule = _due_rule(org, 1, conditions=[{"type": "due_window", "window": "overdue"}])
    late = assigned_task(org.it, EMP_IT, due_date=today - timedelta(days=1))
    older = assigned_task(org.it, EMP_IT, due_date=today - timedelta(days=3))
    done = assigned_task(org.it, EMP_IT, due_date=today - timedelta(days=1), status=Status.DONE)
    assert scheduled.run_due() == 1
    assert late.labels.exists() and not older.labels.exists() and not done.labels.exists()
    assert sorted(statuses(rule)) == ["no_match", "ok"]       # выполненная — условие не сошлось
    assert scheduled.run_due() == 0                             # повтор — ничего
    assert AutomationDueMark.objects.filter(rule=rule).count() == 2


def test_due_command_notifies_every_participant(org):
    """У команды по сроку нет зачинщика: её комментарий получают все участники."""
    _due_rule(org, 1, conditions=[{"type": "due_window", "window": "overdue"}],
              actions_=[{"type": "comment", "text": "@card Просрочено"}])
    assigned_task(org.it, EMP_IT, due_date=context.today() - timedelta(days=1))
    assert scheduled.run_due() == 1
    for user_id in (EMP_IT, HEAD_IT):
        assert Notification.objects.filter(recipient_id=user_id,
                                           title__startswith="Новый комментарий").exists()


def test_due_before_date_and_rescheduled_due_fires_again(org):
    today = context.today()
    rule = _due_rule(org, -2, actions_=[{"type": "comment", "text": "Срок через два дня"}])
    task = assigned_task(org.it, EMP_IT, due_date=today + timedelta(days=2))
    assert scheduled.run_due() == 1
    # Срок перенесли так, что «за два дня» снова сегодня, — другая дата, новая отметка.
    Task.objects.filter(pk=task.pk).update(due_date=today + timedelta(days=2))
    assert scheduled.run_due() == 0
    AutomationDueMark.objects.filter(rule=rule).update(due_date=today + timedelta(days=5))
    assert scheduled.run_due() == 1


def test_due_in_working_days(org):
    today = context.today()
    _due_rule(org, 1, working=True)
    candidate = today - timedelta(days=1)
    task = assigned_task(org.it, EMP_IT, due_date=candidate)
    expected = actions._add_days(candidate, 1, True) == today
    assert scheduled.run_due() == int(expected)
    assert task.labels.exists() is expected


def test_due_ignores_tasks_of_other_boards(org):
    today = context.today()
    _due_rule(org, 0)
    foreign = make_task(department_id=org.ops.id, due_date=today)
    subtree = make_task(department_id=org.dev.id, due_date=today)
    assert scheduled.run_due() == 0
    assert not foreign.labels.exists() and not subtree.labels.exists()


# ── уборка и Celery ─────────────────────────────────────────────────────

def test_purge_removes_old_runs_only(org):
    rule = _due_rule(org, 0)
    old = AutomationRun.objects.create(rule=rule, board_kind="department", board_id=org.it.id,
                                       status="ok", event="due")
    AutomationRun.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=scheduled.RUN_RETENTION_DAYS + 1))
    fresh = AutomationRun.objects.create(rule=rule, board_kind="department", board_id=org.it.id,
                                         status="ok", event="due")
    assert scheduled.purge_runs() >= 1
    assert not AutomationRun.objects.filter(pk=old.pk).exists()
    assert AutomationRun.objects.filter(pk=fresh.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_celery_tasks_run_per_company(company_context):
    slug = company_context["slug"]
    assert celery_tasks.automation_due(company_slug=slug) == 0
    assert celery_tasks.automation_schedule(company_slug=slug) == 0
    assert celery_tasks.automation_runs_purge(company_slug=slug) == 0
