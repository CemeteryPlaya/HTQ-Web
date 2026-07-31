"""Contract tests for ``/api/tasks/v1/reports/*``.

Mirrors ``services/task/app/api/v1/reports.py`` and
``services/gantt_service.py``.
"""

import datetime as dt
from unittest.mock import patch

import pytest
from django.test import Client

from apps.tasks.models import (
    Equipment, EquipmentCategory, Project, Site, Status, Task, ResourceAllocation,
)

from .helpers import BASE, auth

USER = 7
D = dt.date


def _mk_task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S"}
    fields.update(over)
    return Task.objects.create(**fields)


# ── reports/gantt ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reports_gantt_requires_auth():
    assert Client().get(f"{BASE}/reports/gantt").status_code == 401


@pytest.mark.django_db
def test_reports_gantt_bar_shape():
    parent = _mk_task(start_date=D(2026, 3, 2), due_date=D(2026, 3, 6))
    child = _mk_task(parent=parent, start_date=D(2026, 3, 3),
                     status=Status.IN_PROGRESS)
    resp = Client().get(f"{BASE}/reports/gantt", **auth())
    assert resp.status_code == 200
    bars = {b["key"]: b for b in resp.json()["tasks"]}
    assert bars[parent.key]["id"] == str(parent.id)
    assert bars[parent.key]["text"] == parent.summary
    assert bars[parent.key]["start_date"] == "2026-03-02"
    assert bars[parent.key]["end_date"] == "2026-03-06"
    assert bars[parent.key]["progress"] == 0.0
    assert bars[child.key]["parent"] == str(parent.id)
    assert bars[child.key]["progress"] == 0.4      # in_progress
    assert bars[child.key]["assignees"] == []      # never populated, as before


@pytest.mark.django_db
def test_reports_gantt_uses_completion_date_for_closed_tasks():
    task = _mk_task(status=Status.DONE, due_date=D(2026, 3, 10),
                    completed_at=dt.datetime(2026, 3, 8, 12, 0,
                                             tzinfo=dt.timezone.utc))
    bar = Client().get(f"{BASE}/reports/gantt", **auth()).json()["tasks"][0]
    assert bar["end_date"] == "2026-03-08"
    assert bar["progress"] == 1.0


@pytest.mark.django_db
def test_reports_gantt_filters():
    a = _mk_task(status=Status.DONE)
    b = _mk_task(status=Status.TODO)
    resp = Client().get(f"{BASE}/reports/gantt?ids={a.id}", **auth())
    assert [t["id"] for t in resp.json()["tasks"]] == [str(a.id)]

    resp = Client().get(f"{BASE}/reports/gantt?status=todo", **auth())
    assert [t["id"] for t in resp.json()["tasks"]] == [str(b.id)]


@pytest.mark.django_db
def test_reports_gantt_excludes_soft_deleted():
    _mk_task(is_deleted=True)
    assert Client().get(f"{BASE}/reports/gantt",
                        **auth()).json()["tasks"] == []


# ── reports/resource-gantt ──────────────────────────────────────────────

WINDOW = "from=2026-03-01&to=2026-03-31"


@pytest.mark.django_db
def test_resource_gantt_requires_the_window():
    assert Client().get(f"{BASE}/reports/resource-gantt",
                        **auth()).status_code == 422
    assert Client().get(f"{BASE}/reports/resource-gantt?from=nope&to=2026-03-31",
                        **auth()).status_code == 422


@pytest.mark.django_db
def test_resource_gantt_groups_by_employee_and_equipment():
    task = _mk_task(start_date=D(2026, 3, 5), due_date=D(2026, 3, 7))
    # Категория — справочник, а не текст; в ``meta`` она по-прежнему уезжает
    # строкой, что эта же проверка ниже и стережёт.
    equipment = Equipment.objects.create(
        name="Кран", inventory_no="K-1",
        category=EquipmentCategory.objects.create(slug="spectehnika",
                                                  name="Спецтехника"))
    ResourceAllocation.objects.create(task=task, employee_id=11)
    ResourceAllocation.objects.create(task=task, equipment=equipment)

    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[{"id": 11, "username": "i", "email": "i@x",
                              "is_active": True, "full_name": "Иван И"}]):
        resp = Client().get(f"{BASE}/reports/resource-gantt?{WINDOW}", **auth())

    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == {"from": "2026-03-01", "to": "2026-03-31"}
    # employees sort before equipment
    assert [r["resource_kind"] for r in body["resources"]] == ["employee",
                                                              "equipment"]
    emp, eq = body["resources"]
    assert emp["resource_id"] == "emp_11"
    assert emp["resource_name"] == "Иван И"
    assert emp["allocated_tasks"][0]["key"] == task.key
    assert eq["resource_id"] == f"eq_{equipment.id}"
    assert eq["meta"] == {"inventory_no": "K-1", "category": "Спецтехника"}


@pytest.mark.django_db
def test_resource_gantt_falls_back_to_the_primary_assignee():
    """A task with no explicit assignment row still shows the assignee's
    load — otherwise newly created tasks are invisible on this view."""
    task = _mk_task(start_date=D(2026, 3, 5), assignee_id=11)
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[]):
        body = Client().get(f"{BASE}/reports/resource-gantt?{WINDOW}",
                            **auth()).json()
    row = body["resources"][0]
    assert row["resource_id"] == "emp_11"
    # unresolvable name -> stable placeholder, the bar is still useful
    assert row["resource_name"] == "user:11"
    assert row["allocated_tasks"][0]["allocation"] == 100
    assert row["allocated_tasks"][0]["key"] == task.key


@pytest.mark.django_db
def test_resource_gantt_deduplicates_a_task_counted_twice():
    """An employee who is both explicitly assigned and the primary assignee
    must get one bar, not two."""
    task = _mk_task(start_date=D(2026, 3, 5), assignee_id=11)
    ResourceAllocation.objects.create(task=task, employee_id=11, allocation=50)
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[]):
        body = Client().get(f"{BASE}/reports/resource-gantt?{WINDOW}",
                            **auth()).json()
    assert len(body["resources"]) == 1
    tasks = body["resources"][0]["allocated_tasks"]
    assert len(tasks) == 1
    # the explicit assignment wins — it is processed first
    assert tasks[0]["allocation"] == 50


@pytest.mark.django_db
def test_resource_gantt_window_excludes_outside_tasks():
    _mk_task(start_date=D(2026, 1, 5), due_date=D(2026, 1, 9), assignee_id=11)
    _mk_task(assignee_id=12)      # no dates at all -> no bar
    body = Client().get(f"{BASE}/reports/resource-gantt?{WINDOW}",
                        **auth()).json()
    assert body["resources"] == []


@pytest.mark.django_db
def test_resource_gantt_kinds_filter():
    task = _mk_task(start_date=D(2026, 3, 5))
    equipment = Equipment.objects.create(name="Кран")
    ResourceAllocation.objects.create(task=task, employee_id=11)
    ResourceAllocation.objects.create(task=task, equipment=equipment)
    body = Client().get(
        f"{BASE}/reports/resource-gantt?{WINDOW}&kinds=equipment",
        **auth()).json()
    assert [r["resource_kind"] for r in body["resources"]] == ["equipment"]


@pytest.mark.django_db
def test_resource_gantt_search_filters_by_resource_name():
    task = _mk_task(start_date=D(2026, 3, 5))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кран"))
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Погрузчик"))
    body = Client().get(f"{BASE}/reports/resource-gantt?{WINDOW}&search=кран",
                        **auth()).json()
    assert [r["resource_name"] for r in body["resources"]] == ["Кран"]


@pytest.mark.django_db
def test_resource_gantt_department_filter_uses_the_hr_interface():
    task = _mk_task(start_date=D(2026, 3, 5))
    ResourceAllocation.objects.create(task=task, employee_id=11)
    ResourceAllocation.objects.create(task=task, employee_id=12)

    def brief(user_id):
        return {"id": user_id, "department_id": 3 if user_id == 11 else 9}

    with patch("apps.tasks.services.hydration.hr_interface.get_employee_brief",
               side_effect=brief), \
         patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[]):
        body = Client().get(
            f"{BASE}/reports/resource-gantt?{WINDOW}&department_id=3",
            **auth()).json()
    assert [r["resource_id"] for r in body["resources"]] == ["emp_11"]


@pytest.mark.django_db
def test_department_filter_narrows_rather_than_ignores_when_hr_is_down():
    """hr is a stub, so no employee resolves to a department — the filter
    must exclude everyone rather than silently pass everyone through."""
    task = _mk_task(start_date=D(2026, 3, 5))
    ResourceAllocation.objects.create(task=task, employee_id=11)
    body = Client().get(
        f"{BASE}/reports/resource-gantt?{WINDOW}&department_id=3",
        **auth()).json()
    assert body["resources"] == []


# ── ось «проект/объект» в отчётах ───────────────────────────────────────
#
# Оба Ганта научились сужаться по проекту и объекту. В ресурсном это
# особенно важно: фильтр применяется ДО джойна назначений, поэтому строка
# ресурса, у которого нет работы на выбранном объекте, исчезает целиком, а
# не остаётся пустой — иначе график выглядел бы загруженнее, чем он есть.

@pytest.mark.django_db
def test_reports_gantt_filters_by_project():
    project = Project.objects.create(name="Стройка")
    inside = _mk_task(project=project, start_date=D(2026, 1, 1),
                      due_date=D(2026, 1, 10))
    _mk_task(start_date=D(2026, 1, 1), due_date=D(2026, 1, 10))

    body = Client().get(f"{BASE}/reports/gantt?project_id={project.id}",
                        **auth()).json()
    assert [row["id"] for row in body["tasks"]] == [str(inside.id)]


@pytest.mark.django_db
def test_reports_gantt_filters_by_site():
    site = Site.objects.create(name="Алга")
    inside = _mk_task(site=site, start_date=D(2026, 1, 1),
                      due_date=D(2026, 1, 10))
    _mk_task(start_date=D(2026, 1, 1), due_date=D(2026, 1, 10))

    body = Client().get(f"{BASE}/reports/gantt?site_id={site.id}",
                        **auth()).json()
    assert [row["id"] for row in body["tasks"]] == [str(inside.id)]


@pytest.mark.django_db
def test_reports_gantt_combines_project_and_site():
    project = Project.objects.create(name="Стройка")
    alga = Site.objects.create(name="Алга")
    sazagan = Site.objects.create(name="Сазаган")
    wanted = _mk_task(project=project, site=alga,
                      start_date=D(2026, 1, 1), due_date=D(2026, 1, 10))
    _mk_task(project=project, site=sazagan,
             start_date=D(2026, 1, 1), due_date=D(2026, 1, 10))

    body = Client().get(
        f"{BASE}/reports/gantt?project_id={project.id}&site_id={alga.id}",
        **auth()).json()
    assert [row["id"] for row in body["tasks"]] == [str(wanted.id)]


@pytest.mark.django_db
def test_resource_gantt_project_filter_drops_the_whole_row():
    """Именно строку, а не только полосу: пустая строка ресурса читалась бы
    как «человек занят», хотя на этом проекте у него работы нет."""
    project = Project.objects.create(name="Стройка")
    _mk_task(project=project, assignee_id=USER,
             start_date=D(2026, 1, 5), due_date=D(2026, 1, 8))
    _mk_task(assignee_id=99, start_date=D(2026, 1, 5), due_date=D(2026, 1, 8))

    body = Client().get(
        f"{BASE}/reports/resource-gantt?from=2026-01-01&to=2026-01-31"
        f"&project_id={project.id}", **auth()).json()
    assert [r["resource_id"] for r in body["resources"]] == [f"emp_{USER}"]


@pytest.mark.django_db
def test_resource_gantt_site_filter_narrows_equipment_rows_too():
    site = Site.objects.create(name="Алга")
    crane = Equipment.objects.create(name="Кран")
    digger = Equipment.objects.create(name="Экскаватор")
    on_site = _mk_task(site=site, start_date=D(2026, 1, 5),
                       due_date=D(2026, 1, 8))
    elsewhere = _mk_task(start_date=D(2026, 1, 5), due_date=D(2026, 1, 8))
    ResourceAllocation.objects.create(task=on_site, equipment=crane)
    ResourceAllocation.objects.create(task=elsewhere, equipment=digger)

    body = Client().get(
        f"{BASE}/reports/resource-gantt?from=2026-01-01&to=2026-01-31"
        f"&site_id={site.id}", **auth()).json()
    assert [r["resource_name"] for r in body["resources"]] == ["Кран"]


@pytest.mark.django_db
def test_gantt_filters_reject_a_non_numeric_id():
    """422-конверт, а не 500 из int()."""
    assert Client().get(f"{BASE}/reports/gantt?site_id=abc",
                        **auth()).status_code == 422
    assert Client().get(
        f"{BASE}/reports/resource-gantt?from=2026-01-01&to=2026-01-31"
        f"&project_id=abc", **auth()).status_code == 422
