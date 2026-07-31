"""Ресурсы: потребность количеством против именных назначений.

Ровно тот разрыв, который на доске записан как «2 человека, 2 кары» на
роудмапе и «1 человек, 1 кара» на задаче: сверху план числами, снизу
конкретные люди и машины.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import (Equipment, EquipmentCategory, Project,
                               ProjectSite, ResourceAllocation, ResourceKind,
                               ResourceRequirement, Roadmap, Site, SiteBlock,
                               Task, WorkRole)

from .helpers import BASE, admin_token, auth, post_json, token


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
    return Roadmap.objects.create(project=project, site_block=block,
                                  owner_id=9, name="Развозка валов")


@pytest.fixture
def kara(db) -> EquipmentCategory:
    return EquipmentCategory.objects.create(slug="kara", name="Кара")


# ── потребность количеством ─────────────────────────────────────────────

@pytest.mark.django_db
def test_roadmap_requirement_is_a_quantity_not_a_name(roadmap, kara):
    """«2 кары (вилопогрузчик)» — тип и число, без инвентарных номеров."""
    resp = post_json(Client(), f"{BASE}/resource-requirements/",
                     {"roadmap_id": roadmap.id, "kind": "equipment",
                      "equipment_category_id": kara.id, "quantity": 2},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert (body["quantity"], body["filled"]) == (2, 0)
    assert body["equipment_category_name"] == "Кара"
    assert body["work_role_id"] is None


@pytest.mark.django_db
def test_human_requirement_without_a_role_is_valid(roadmap):
    """«Нужно 2 человека, роль не важна» — законный план."""
    resp = post_json(Client(), f"{BASE}/resource-requirements/",
                     {"roadmap_id": roadmap.id, "kind": "human",
                      "quantity": 2}, **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["quantity"] == 2


@pytest.mark.django_db
def test_requirement_clears_the_field_of_the_other_kind(roadmap, kara):
    """Форма шлёт обе колонки; переключение вида — не ошибка оператора."""
    resp = post_json(Client(), f"{BASE}/resource-requirements/",
                     {"roadmap_id": roadmap.id, "kind": "human",
                      "equipment_category_id": kara.id, "quantity": 1},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["equipment_category_id"] is None


@pytest.mark.django_db
def test_requirement_needs_exactly_one_target(roadmap):
    task = Task.objects.create(key="TASK-1", summary="A")
    hdr = auth(admin_token())
    both = post_json(Client(), f"{BASE}/resource-requirements/",
                     {"roadmap_id": roadmap.id, "task_id": task.id,
                      "kind": "human"}, **hdr)
    neither = post_json(Client(), f"{BASE}/resource-requirements/",
                        {"kind": "human"}, **hdr)
    assert both.status_code == 422
    assert neither.status_code == 422


@pytest.mark.django_db
def test_task_level_requirement_lives_on_the_task(roadmap):
    """Та же тройка ниже уровнем: «на эту задачу — 1 человек»."""
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               reporter_id=9)
    resp = post_json(Client(), f"{BASE}/resource-requirements/",
                     {"task_id": task.id, "kind": "human", "quantity": 1},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["task_id"] == task.id


@pytest.mark.django_db
def test_requirements_are_listed_per_target(roadmap, kara):
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.EQUIPMENT,
                                       equipment_category=kara, quantity=2)
    resp = Client().get(f"{BASE}/resource-requirements/?roadmap_id={roadmap.id}",
                        **auth(admin_token()))
    assert [r["quantity"] for r in resp.json()] == [2]


@pytest.mark.django_db
def test_requirement_list_needs_exactly_one_target():
    resp = Client().get(f"{BASE}/resource-requirements/", **auth(admin_token()))
    assert resp.status_code == 422


# ── именные назначения поверх плана ─────────────────────────────────────

@pytest.mark.django_db
def test_allocation_can_close_a_requirement(roadmap, kara):
    req = ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.EQUIPMENT,
        equipment_category=kara, quantity=2)
    machine = Equipment.objects.create(name="Кара K-1", category=kara)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "equipment_id": machine.id,
                      "requirement_id": req.id}, **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["requirement_id"] == req.id

    listing = Client().get(
        f"{BASE}/resource-requirements/?roadmap_id={roadmap.id}",
        **auth(admin_token())).json()
    assert listing[0]["filled"] == 1


@pytest.mark.django_db
def test_allocation_cannot_overfill_a_requirement(roadmap, kara):
    """«Закрыто 3 из 2» — недостижимое состояние, иначе метрика показывала
    бы перевыполнение там, где просто кликнули лишний раз."""
    req = ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.EQUIPMENT,
        equipment_category=kara, quantity=1)
    first = Equipment.objects.create(name="Кара K-1", category=kara)
    second = Equipment.objects.create(name="Кара K-2", category=kara)
    hdr = auth(admin_token())
    post_json(Client(), f"{BASE}/assignments/",
              {"roadmap_id": roadmap.id, "equipment_id": first.id,
               "requirement_id": req.id}, **hdr)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "equipment_id": second.id,
                      "requirement_id": req.id}, **hdr)
    assert resp.status_code == 422
    # Сообщение называет РЕАЛЬНОЕ число закрытых мест, а не повторяет план
    # дважды: «назначено 1 из 1» читается, «назначено 1 из 1» при плане 3 —
    # нет.
    assert "1 из 1" in resp.json()["detail"]


@pytest.mark.django_db
def test_allocation_kind_must_match_the_requirement(roadmap, kara):
    req = ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.EQUIPMENT,
        equipment_category=kara, quantity=2)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "employee_id": 11,
                      "requirement_id": req.id}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_allocation_requirement_must_share_the_target(roadmap, kara, project,
                                                      block):
    other = Roadmap.objects.create(project=project, site_block=block,
                                   name="Монтаж")
    req = ResourceRequirement.objects.create(
        roadmap=other, kind=ResourceKind.HUMAN, quantity=2)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "employee_id": 11,
                      "requirement_id": req.id}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_allocation_without_a_requirement_is_fine(roadmap):
    """Назначить ресурс, не планировав его заранее, — нормальный ход дел."""
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "employee_id": 11},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["requirement_id"] is None


@pytest.mark.django_db
def test_deleting_a_requirement_keeps_its_allocations(roadmap):
    """SET_NULL: снять план можно, потерять вместе с ним работающих — нет."""
    req = ResourceRequirement.objects.create(roadmap=roadmap,
                                             kind=ResourceKind.HUMAN,
                                             quantity=1)
    row = ResourceAllocation.objects.create(roadmap=roadmap, employee_id=11,
                                            requirement=req)
    assert Client().delete(f"{BASE}/resource-requirements/{req.id}",
                           **auth(admin_token())).status_code == 204
    row.refresh_from_db()
    assert row.requirement_id is None


# ── старый контракт назначений на задачу не сломан ──────────────────────

@pytest.mark.django_db
def test_task_assignment_still_works_with_only_task_id():
    """Старый клиент шлёт только task_id и обязан продолжать работать."""
    task = Task.objects.create(key="TASK-1", summary="A", reporter_id=7)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "employee_id": 11, "role": "сварщик"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert (body["task_id"], body["roadmap_id"]) == (task.id, None)

    listing = Client().get(f"{BASE}/assignments/?task_id={task.id}",
                           **auth(admin_token())).json()
    assert [r["employee_id"] for r in listing] == [11]


@pytest.mark.django_db
def test_assignment_still_requires_exactly_one_resource():
    task = Task.objects.create(key="TASK-1", summary="A", reporter_id=7)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_assignment_needs_exactly_one_target():
    task = Task.objects.create(key="TASK-1", summary="A", reporter_id=7)
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "roadmap_id": 1, "employee_id": 11},
                     **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_roadmap_allocations_are_admin_or_owner_only(roadmap):
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"roadmap_id": roadmap.id, "employee_id": 11},
                     **auth(token()))
    assert resp.status_code in (403, 404)


# ── метрика роудмапа: план против факта по ресурсам ─────────────────────

@pytest.mark.django_db
def test_metrics_compare_planned_quantity_with_named_reality(roadmap, kara):
    """Доска целиком: план 2 человека / 2 кары, по факту 1 и 1."""
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.HUMAN, quantity=2)
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.EQUIPMENT,
                                       equipment_category=kara, quantity=2)
    machine = Equipment.objects.create(name="Кара K-1", category=kara)
    task = Task.objects.create(key="TASK-1", summary="Развезти валов",
                               roadmap=roadmap, assignee_id=11)
    ResourceAllocation.objects.create(task=task, equipment=machine)

    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"] == {"planned": 2, "actual": 1, "delta": -1}
    assert body["equipment"] == {"planned": 2, "actual": 1, "delta": -1}


@pytest.mark.django_db
def test_metrics_count_one_person_once_across_tasks(roadmap):
    """Один человек на трёх задачах пакета — это один человек."""
    for key in ("TASK-1", "TASK-2", "TASK-3"):
        task = Task.objects.create(key=key, summary=key, roadmap=roadmap)
        ResourceAllocation.objects.create(task=task, employee_id=11)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"]["actual"] == 1


@pytest.mark.django_db
def test_metrics_count_task_assignees_without_allocation_rows(roadmap):
    """У задачи может не быть строки назначения, но исполнитель есть — и он
    занят, значит входит в «сколько людей на пакете»."""
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        assignee_id=42)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"]["actual"] == 1


@pytest.mark.django_db
def test_metrics_ignore_resources_of_deleted_tasks(roadmap):
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               is_deleted=True)
    ResourceAllocation.objects.create(task=task, employee_id=11)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"]["actual"] == 0


@pytest.mark.django_db
def test_metrics_planned_stays_none_without_requirements(roadmap):
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        assignee_id=11)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"] == {"planned": None, "actual": 1, "delta": None}


@pytest.mark.django_db
def test_metrics_do_not_double_count_task_level_requirements(roadmap):
    """Потребности задач — детализация того же плана уровнем ниже; сложение
    с планом роудмапа дало бы двойной счёт."""
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.HUMAN, quantity=2)
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap)
    ResourceRequirement.objects.create(task=task, kind=ResourceKind.HUMAN,
                                       quantity=1)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["human"]["planned"] == 2


@pytest.mark.django_db
def test_roadmap_allocation_does_not_appear_on_the_resource_gantt(roadmap):
    """Ресурсный Гант рисует полосы по задачам; у назначения на пакет
    задачи нет, и рисовать нечего — но и падать не должно."""
    ResourceAllocation.objects.create(roadmap=roadmap, employee_id=11)
    resp = Client().get(
        f"{BASE}/reports/resource-gantt?from=2026-01-01&to=2026-12-31",
        **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["resources"] == []
