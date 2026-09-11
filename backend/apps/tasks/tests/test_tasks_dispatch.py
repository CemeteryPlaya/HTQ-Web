"""Диспетчеры tasks-домена — веер по действующим компаниям.

Закрывает docs/multi-company-tenancy-followups.md п.1 для
``task_deadline_reminder`` и ``calendar_event_reminder``: у Celery-задачи
нет HTTP-запроса, поэтому оба реальных ``@company_task`` не могут сами
выбрать себе компанию. beat планирует ``task_deadline_reminder_dispatch`` /
``calendar_event_reminder_dispatch`` без компании — те читают
``active_company_slugs()`` и веером ставят реальную задачу на каждую
действующую компанию, сбой постановки для одной не останавливает обход
остальных.
"""
from __future__ import annotations

import pytest

import apps.tasks.tasks as tasks_celery
from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled


def _disable_tasks():
    ServiceStatus.objects.update_or_create(app_label="tasks",
                                           defaults={"enabled": False})


# ── task_deadline_reminder_dispatch ─────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_deadline_dispatch_fans_out_to_every_active_company(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []
    monkeypatch.setattr(tasks_celery.task_deadline_reminder, "delay",
                        lambda *, company_slug: seen.append(company_slug))

    result = tasks_celery.task_deadline_reminder_dispatch()

    assert seen == sorted([alpha, beta])
    assert result == {"dispatched": sorted([alpha, beta]), "failed": []}


@pytest.mark.django_db(transaction=True)
def test_deadline_dispatch_keeps_going_after_one_company_fails(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []

    def fake_delay(*, company_slug):
        if company_slug == alpha:
            raise RuntimeError("broker unavailable")
        seen.append(company_slug)

    monkeypatch.setattr(tasks_celery.task_deadline_reminder, "delay", fake_delay)

    result = tasks_celery.task_deadline_reminder_dispatch()

    assert seen == [beta]
    assert result == {"dispatched": [beta], "failed": [alpha]}


@pytest.mark.django_db
def test_deadline_dispatch_refuses_to_run_when_the_service_is_off():
    _disable_tasks()
    with pytest.raises(ServiceDisabled):
        tasks_celery.task_deadline_reminder_dispatch()


# ── calendar_event_reminder_dispatch ────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_calendar_dispatch_fans_out_to_every_active_company(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []
    monkeypatch.setattr(tasks_celery.calendar_event_reminder, "delay",
                        lambda *, company_slug: seen.append(company_slug))

    result = tasks_celery.calendar_event_reminder_dispatch()

    assert seen == sorted([alpha, beta])
    assert result == {"dispatched": sorted([alpha, beta]), "failed": []}


@pytest.mark.django_db(transaction=True)
def test_calendar_dispatch_keeps_going_after_one_company_fails(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []

    def fake_delay(*, company_slug):
        if company_slug == alpha:
            raise RuntimeError("broker unavailable")
        seen.append(company_slug)

    monkeypatch.setattr(tasks_celery.calendar_event_reminder, "delay", fake_delay)

    result = tasks_celery.calendar_event_reminder_dispatch()

    assert seen == [beta]
    assert result == {"dispatched": [beta], "failed": [alpha]}


@pytest.mark.django_db
def test_calendar_dispatch_refuses_to_run_when_the_service_is_off():
    _disable_tasks()
    with pytest.raises(ServiceDisabled):
        tasks_celery.calendar_event_reminder_dispatch()
