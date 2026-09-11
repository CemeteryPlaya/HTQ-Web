"""Диспетчер ``sync_identity_dispatch`` — веер по действующим компаниям.

Закрывает п.1 docs/multi-company-tenancy-followups.md: у Celery-задачи нет
HTTP-запроса, поэтому реальная ``sync_identity`` не может сама выбрать себе
компанию — beat планирует диспетчера, тот веером ставит ``sync_identity`` на
каждую ДЕЙСТВУЮЩУЮ компанию (``active_company_slugs``), передавая
``company_slug`` именованным аргументом. Сбой постановки для одной компании
не должен останавливать обход остальных.
"""
from __future__ import annotations

import pytest

import apps.hr.tasks as hr_tasks


@pytest.mark.django_db(transaction=True)
def test_dispatch_fans_out_to_every_active_company(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []

    def fake_delay(*, company_slug):
        seen.append(company_slug)

    monkeypatch.setattr(hr_tasks.sync_identity, "delay", fake_delay)

    result = hr_tasks.sync_identity_dispatch()

    assert seen == sorted([alpha, beta])
    assert result == {"dispatched": sorted([alpha, beta]), "failed": []}


@pytest.mark.django_db(transaction=True)
def test_dispatch_keeps_going_after_one_company_fails(two_company_schemas, monkeypatch):
    alpha, beta = two_company_schemas
    seen: list[str] = []

    def fake_delay(*, company_slug):
        if company_slug == alpha:
            raise RuntimeError("broker unavailable")
        seen.append(company_slug)

    monkeypatch.setattr(hr_tasks.sync_identity, "delay", fake_delay)

    result = hr_tasks.sync_identity_dispatch()

    assert seen == [beta]
    assert result == {"dispatched": [beta], "failed": [alpha]}


@pytest.mark.django_db
def test_dispatch_refuses_to_run_when_the_service_is_off():
    from apps.core.models import ServiceStatus
    from apps.core.services import ServiceDisabled

    ServiceStatus.objects.update_or_create(app_label="hr", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        hr_tasks.sync_identity_dispatch()


@pytest.mark.django_db
def test_beat_schedule_points_at_the_dispatcher_not_the_real_task():
    """Расписание переведено на диспетчера (followups.md п.1): миграция
    ``0020_sync_identity_dispatch_periodic_task`` перекладывает
    ``PeriodicTask.task`` на ``sync_identity_dispatch``, иначе beat каждую
    ночь звал бы ``sync_identity`` без company_slug и получал бы
    MissingCompanyArgument."""
    from django_celery_beat.models import PeriodicTask

    row = PeriodicTask.objects.get(name="hr.sync_identity")
    assert row.task == "apps.hr.tasks.sync_identity_dispatch"
    assert row.enabled is True
