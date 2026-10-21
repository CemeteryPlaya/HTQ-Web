"""Задачи мимо видимости — закрыто (канбан K1.4, спека этапа 1 S1-17).

Лента календаря и Ганта отчётов отдавали любые задачи без проверки
видимости, карточка — заголовки связанных задач и подзадачи без неё же.
Теперь все четыре идут через ту же видимость, что список и карточка.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import LinkType, TaskLink

from .helpers import BASE, admin_token, auth
from .org_fixtures import EMP_IT, HEAD_IT, OD, OUTSIDER, as_user, make_org, make_task

pytestmark = pytest.mark.django_db

DAY = dt.date(2026, 10, 15)


@pytest.fixture
def org():
    return make_org()


def _private(**fields):
    return make_task(reporter_id=OUTSIDER, assignee_id=OUTSIDER, start_date=DAY,
                     due_date=DAY, summary="Личное OUTSIDER", **fields)


@pytest.mark.parametrize("viewer", [EMP_IT, OD, HEAD_IT])
def test_calendar_timeline_hides_invisible_tasks(org, viewer):
    private = _private()
    own = make_task(department_id=org.it.id, start_date=DAY, due_date=DAY)
    response = Client().get(f"{BASE}/calendar/timeline/?start=2026-10-01&end=2026-10-31",
                            **as_user(viewer))
    assert response.status_code == 200, response.content
    ids = {int(row["id"]) for row in response.json()["tasks"]}
    assert private.pk not in ids
    if viewer != OD:
        assert own.pk in ids


@pytest.mark.parametrize("viewer", [EMP_IT, OD, HEAD_IT])
def test_reports_gantt_hides_invisible_tasks(org, viewer):
    private = _private()
    response = Client().get(f"{BASE}/reports/gantt?ids={private.pk}", **as_user(viewer))
    assert response.status_code == 200, response.content
    assert response.json()["tasks"] == []


def test_elevated_still_sees_private_on_timeline_and_gantt(org):
    private = _private()
    timeline = Client().get(f"{BASE}/calendar/timeline/?start=2026-10-01&end=2026-10-31",
                            **auth(admin_token()))
    assert private.pk in {int(row["id"]) for row in timeline.json()["tasks"]}
    gantt = Client().get(f"{BASE}/reports/gantt?ids={private.pk}", **auth(admin_token()))
    assert [row["id"] for row in gantt.json()["tasks"]] == [str(private.pk)]


def test_card_hides_links_to_invisible_tasks(org):
    visible = make_task(department_id=org.it.id)
    private = _private()
    TaskLink.objects.create(source=visible, target=private, link_type=LinkType.RELATES_TO)
    TaskLink.objects.create(source=private, target=visible, link_type=LinkType.BLOCKS)
    body = Client().get(f"{BASE}/tasks/{visible.pk}/", **as_user(EMP_IT)).json()
    assert body["outgoing_links"] == []
    assert body["incoming_links"] == []
    assert "Личное OUTSIDER" not in str(body)


def test_card_hides_invisible_subtasks(org):
    parent = make_task(department_id=org.it.id)
    hidden = _private(parent=parent)
    shown = make_task(department_id=org.it.id, parent=parent)
    body = Client().get(f"{BASE}/tasks/{parent.pk}/", **as_user(EMP_IT)).json()
    assert [row["id"] for row in body["subtasks"]] == [shown.pk]
    assert hidden.pk not in [row["id"] for row in body["subtasks"]]


def test_elevated_card_shows_everything(org):
    parent = make_task(department_id=org.it.id)
    private = _private(parent=parent)
    TaskLink.objects.create(source=parent, target=private, link_type=LinkType.RELATES_TO)
    body = Client().get(f"{BASE}/tasks/{parent.pk}/", **auth(admin_token())).json()
    assert [row["id"] for row in body["subtasks"]] == [private.pk]
    assert len(body["outgoing_links"]) == 1


def _allocated(viewer_headers) -> set[int]:
    body = Client().get(f"{BASE}/reports/resource-gantt?from=2026-10-01&to=2026-10-31",
                        **viewer_headers).json()
    return {int(task["task_id"]) for row in body["resources"]
            for task in row["allocated_tasks"]}


def test_resource_gantt_hides_invisible_tasks(org):
    """Полосы ресурсов отдавали заголовки любых задач — та же утечка (S1-17)."""
    from apps.tasks.models import Equipment, ResourceAllocation

    private = _private()
    own = make_task(department_id=org.it.id, start_date=DAY, due_date=DAY)
    crane = Equipment.objects.create(name="Кран K1.4")
    ResourceAllocation.objects.create(task=private, equipment=crane)
    ResourceAllocation.objects.create(task=own, equipment=crane)
    assert _allocated(as_user(EMP_IT)) == {own.pk}
    assert _allocated(as_user(OD)) == {own.pk}
    assert _allocated(auth(admin_token())) == {own.pk, private.pk}
