"""Серверные вкладки списка задач ``?scope=mine|department`` (канбан K1.6, S1-04).

После расширения видимости (K1.4) вкладки ``EmployeeTasks``, фильтровавшие
первые 50 задач на клиенте, теряли бы свои задачи: задачи отдела вытесняют
их из первой страницы. Сервер отбирает сам.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone

from apps.tasks.models import Task

from .helpers import BASE
from .org_fixtures import EMP_IT, OUTSIDER, TD, as_user, make_board, make_org, make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _ids(user_id, query) -> list[int]:
    response = Client().get(f"{BASE}/tasks/?{query}", **as_user(user_id))
    assert response.status_code == 200, response.content
    return [row["id"] for row in response.json()]


def test_mine_finds_own_task_behind_sixty_department_tasks(org):
    own = make_task(reporter_id=EMP_IT)
    for _ in range(60):
        make_task(department_id=org.dev.id, assignee_id=OUTSIDER)
    now = timezone.now()
    Task.objects.filter(pk=own.pk).update(created_at=now - dt.timedelta(days=1))
    Task.objects.exclude(pk=own.pk).update(created_at=now)
    assert own.pk not in _ids(EMP_IT, "limit=50")          # контроль: без scope вытеснена
    assert _ids(EMP_IT, "limit=50&scope=mine") == [own.pk]


def test_mine_includes_watching_and_delegation(org):
    from apps.tasks.models import TaskDelegate, TaskWatcher
    watched = make_task(reporter_id=OUTSIDER)
    TaskWatcher.objects.create(task=watched, user_id=EMP_IT)
    delegated = make_task(reporter_id=OUTSIDER)
    TaskDelegate.objects.create(task=delegated, user_id=EMP_IT)
    assert set(_ids(EMP_IT, "scope=mine")) == {watched.pk, delegated.pk}


def test_department_excludes_board_only_tasks(org):
    in_dept = make_task(department_id=org.dev.id)
    board = make_board("П-LS")
    on_board = make_task(project=board)
    ids = _ids(TD, "scope=department")
    assert on_board.pk not in ids
    assert in_dept.pk in _ids(EMP_IT, "scope=department")


def test_unknown_scope_is_422(org):
    response = Client().get(f"{BASE}/tasks/?scope=x", **as_user(EMP_IT))
    assert response.status_code == 422


def test_department_tab_for_elevated_is_unfiltered(org):
    from .helpers import admin_token, auth
    task = make_task(department_id=org.ops.id)
    response = Client().get(f"{BASE}/tasks/?scope=department", **auth(admin_token()))
    assert task.pk in [row["id"] for row in response.json()]
