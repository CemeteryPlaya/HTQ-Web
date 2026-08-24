"""Учёт задействования техники и наследование партнёра.

Оба сюжета из SPEC §10 закрываются БЕЗ новых таблиц:

* «какая техника задействована на дату D» и история интервалов считаются по
  существующим ``ResourceRequirement(kind=equipment)`` и
  ``ResourceAllocation`` — спека предлагала завести под это отдельный
  ``EquipmentEngagement``, но это поле в поле уже существующая потребность;
* эффективный партнёр разрешается по ``ContractorEngagement``, который уже
  ключуется на проект, площадку и роудмап.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (Contractor, ContractorEngagement, Equipment,
                               EquipmentCategory, Project, ProjectSite,
                               ResourceAllocation, ResourceKind,
                               ResourceRequirement, Roadmap, Site, SiteBlock,
                               Task)

from .helpers import BASE, admin_token, auth

D = dt.date


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="Солнечный парк", owner_id=9)


@pytest.fixture
def site(db, project) -> Site:
    site = Site.objects.create(name="Сазаган")
    ProjectSite.objects.create(project=project, site=site, is_primary=True)
    return site


@pytest.fixture
def block(db, site) -> SiteBlock:
    return SiteBlock.objects.create(site=site, name="Блок 1", order=1)


@pytest.fixture
def roadmap(db, project, block) -> Roadmap:
    return Roadmap.objects.create(
        project=project, site_block=block, owner_id=9, name="Развозка валов",
        planned_start_date=D(2026, 6, 1), planned_end_date=D(2026, 6, 30))


@pytest.fixture
def kara(db) -> EquipmentCategory:
    return EquipmentCategory.objects.create(slug="kara", name="Кара")


# ── что задействовано на дату D ─────────────────────────────────────────

@pytest.mark.django_db
def test_engaged_on_reports_plan_and_fact_side_by_side(roadmap, kara):
    """«Нужно 2 кары, выделена 1» — рабочий ответ; одна цифра вводит в
    заблуждение, поэтому отдаются обе."""
    ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.EQUIPMENT, equipment_category=kara,
        quantity=2, start_date=D(2026, 6, 1), end_date=D(2026, 6, 20))
    ResourceAllocation.objects.create(
        roadmap=roadmap, equipment=Equipment.objects.create(
            name="Кара K-1", category=kara))

    body = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&date=2026-06-10",
        **auth(admin_token())).json()
    assert body["engaged"] == [{"category_id": kara.id, "category_name": "Кара",
                                "planned": 2, "assigned": 1}]


@pytest.mark.django_db
def test_engaged_on_excludes_a_date_outside_the_period(roadmap, kara):
    ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.EQUIPMENT, equipment_category=kara,
        quantity=2, start_date=D(2026, 6, 1), end_date=D(2026, 6, 10))
    hdr = auth(admin_token())
    inside = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&date=2026-06-05",
        **hdr).json()
    outside = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&date=2026-06-25",
        **hdr).json()
    assert inside["engaged"][0]["planned"] == 2
    assert outside["engaged"] == []


@pytest.mark.django_db
def test_allocation_without_dates_inherits_the_period_of_its_task(roadmap, kara):
    """У именного назначения своих дат нет — оно занято ровно столько,
    сколько идёт его задача."""
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               start_date=D(2026, 6, 3),
                               due_date=D(2026, 6, 7))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кара K-1",
                                                      category=kara))
    hdr = auth(admin_token())
    inside = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&date=2026-06-05",
        **hdr).json()
    outside = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&date=2026-06-20",
        **hdr).json()
    assert inside["engaged"][0]["assigned"] == 1
    assert outside["engaged"] == []


@pytest.mark.django_db
def test_engaged_rolls_up_from_tasks_to_the_site(roadmap, site, kara):
    """Занятость поднимается вверх по иерархии: спросили площадку —
    получили и то, что стоит на её задачах."""
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               site=site, start_date=D(2026, 6, 1),
                               due_date=D(2026, 6, 30))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кара K-1",
                                                      category=kara))
    body = Client().get(
        f"{BASE}/equipment-usage?site_id={site.id}&date=2026-06-10",
        **auth(admin_token())).json()
    assert body["engaged"][0]["assigned"] == 1


@pytest.mark.django_db
def test_equipment_usage_needs_exactly_one_scope(roadmap):
    hdr = auth(admin_token())
    assert Client().get(f"{BASE}/equipment-usage", **hdr).status_code == 422
    assert Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}&task_id=1",
        **hdr).status_code == 422


# ── история интервалов ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_history_returns_intervals_not_days(roadmap, kara):
    """«Кара K-1 стояла с 3 по 7 июня» — одна строка, а не пять."""
    task = Task.objects.create(key="TASK-1", summary="Развозка валов",
                               roadmap=roadmap, start_date=D(2026, 6, 3),
                               due_date=D(2026, 6, 7))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(
            name="Кара K-1", inventory_no="K-1", category=kara))

    body = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}"
        f"&date_from=2026-06-01&date_to=2026-06-30",
        **auth(admin_token())).json()
    assert len(body["history"]) == 1
    row = body["history"][0]
    assert (row["date_from"], row["date_to"]) == ("2026-06-03", "2026-06-07")
    assert row["days"] == 5
    assert row["inventory_no"] == "K-1"
    assert row["task_key"] == "TASK-1"


@pytest.mark.django_db
def test_history_can_be_narrowed_to_one_category(roadmap, kara):
    crane = EquipmentCategory.objects.create(slug="kran", name="Кран")
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               start_date=D(2026, 6, 3), due_date=D(2026, 6, 7))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кара", category=kara))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="КС-45",
                                                      category=crane))
    body = Client().get(
        f"{BASE}/equipment-usage?roadmap_id={roadmap.id}"
        f"&date_from=2026-06-01&date_to=2026-06-30&category_id={crane.id}",
        **auth(admin_token())).json()
    assert [r["equipment_name"] for r in body["history"]] == ["КС-45"]


@pytest.mark.django_db
def test_history_skips_allocations_with_no_dates_at_all(roadmap, kara):
    """У задачи без дат периода нет, и показывать её технику «занятой
    всегда» нельзя."""
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=None)
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кара",
                                                      category=kara))
    body = Client().get(
        f"{BASE}/equipment-usage?task_id={task.id}"
        f"&date_from=2026-06-01&date_to=2026-06-30",
        **auth(admin_token())).json()
    assert body["history"] == []


# ── наследование партнёра ─────────────────────────────────────────────

@pytest.mark.django_db
def test_effective_contractor_is_inherited_from_the_roadmap(roadmap):
    """Партнёра назначают на пакет работ, а не задача за задачей."""
    org = Contractor.objects.create(name="СтройПодряд")
    ContractorEngagement.objects.create(contractor=org, roadmap=roadmap)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap)

    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["contractor_id"] is None          # своего нет
    assert body["effective_contractor"] == {"id": org.id, "name": "СтройПодряд"}


@pytest.mark.django_db
def test_own_contractor_beats_the_inherited_one(roadmap):
    inherited = Contractor.objects.create(name="СтройПодряд")
    own = Contractor.objects.create(name="Личный")
    ContractorEngagement.objects.create(contractor=inherited, roadmap=roadmap)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               contractor=own)

    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["effective_contractor"] == {"id": own.id, "name": "Личный"}


@pytest.mark.django_db
def test_roadmap_engagement_beats_the_project_one(project, roadmap):
    """От частного к общему: пакет ближе задачи, чем проект."""
    wide = Contractor.objects.create(name="Генподряд")
    narrow = Contractor.objects.create(name="СтройПодряд")
    ContractorEngagement.objects.create(contractor=wide, project=project)
    ContractorEngagement.objects.create(contractor=narrow, roadmap=roadmap)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               project=project)

    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["effective_contractor"]["name"] == "СтройПодряд"


@pytest.mark.django_db
def test_site_engagement_is_inherited_when_the_roadmap_has_none(site, roadmap):
    org = Contractor.objects.create(name="СтройПодряд")
    ContractorEngagement.objects.create(contractor=org, site=site)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               site=site)

    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["effective_contractor"]["id"] == org.id


@pytest.mark.django_db
def test_inactive_engagement_is_not_inherited(roadmap):
    org = Contractor.objects.create(name="СтройПодряд")
    ContractorEngagement.objects.create(contractor=org, roadmap=roadmap,
                                        is_active=False)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap)

    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["effective_contractor"] is None


@pytest.mark.django_db
def test_no_engagement_anywhere_means_own_crew(roadmap):
    """None — это «своя команда», первоклассное состояние, а не пробел."""
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap)
    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["effective_contractor"] is None


@pytest.mark.django_db
def test_effective_contractor_is_resolved_for_the_whole_list_at_once(
        django_assert_num_queries, roadmap):
    """Разрешение — батчем: инвариант task_response про одну волну на
    список, а не запрос на задачу."""
    org = Contractor.objects.create(name="СтройПодряд")
    ContractorEngagement.objects.create(contractor=org, roadmap=roadmap)
    for index in range(5):
        Task.objects.create(key=f"TASK-{index}", summary="A", roadmap=roadmap)

    body = Client().get(f"{BASE}/tasks/", **auth(admin_token())).json()
    assert len(body) == 5
    assert all(row["effective_contractor"]["id"] == org.id for row in body)
