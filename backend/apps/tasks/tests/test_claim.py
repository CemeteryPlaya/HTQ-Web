"""«Взять в работу» (канбан K1.6, спека §K1.5, S1-07).

Сотрудник берёт неразобранную задачу своего отдела или подотдела (основной
отдел или связь-участник): становится основным исполнителем, задача уходит в
«В работе». Через «все отделы», доску проекта или связь-отправителя — нельзя.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection
from django.test import Client

from apps.tasks.models import Status, Task, TaskAssignee, TaskActivity, TaskDepartmentLink

from .helpers import BASE, post_json
from .org_fixtures import (EMP_DEV, EMP_IT, OD, TD, as_user, make_board, make_org,
                           make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _claim(user_id, task_id):
    return post_json(Client(), f"{BASE}/tasks/{task_id}/claim/", {}, **as_user(user_id))


def test_member_claims_unassigned_subdept_task(org):
    task = make_task(department_id=org.dev.id, status=Status.TODO)
    response = _claim(EMP_IT, task.pk)
    assert response.status_code == 200, response.content
    task.refresh_from_db()
    assert task.assignee_id == EMP_IT
    assert task.status == Status.IN_PROGRESS
    assert TaskAssignee.objects.get(task=task).role == "primary"
    assert TaskActivity.objects.filter(task=task, field_name="claim").exists()


def test_claim_via_member_link(org):
    task = make_task(department_id=org.ops.id, status=Status.BACKLOG)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id)
    assert _claim(EMP_IT, task.pk).status_code == 200


def test_claim_with_assignee_is_409(org):
    task = make_task(department_id=org.it.id, assignee_id=EMP_DEV)
    response = _claim(EMP_IT, task.pk)
    assert response.status_code == 409
    assert response.json()["code"] == "task_claim_unavailable"


def test_claim_in_progress_is_409(org):
    task = make_task(department_id=org.it.id, status=Status.IN_PROGRESS)
    assert _claim(EMP_IT, task.pk).status_code == 409


def test_claim_via_project_board_is_403(org):
    board = make_board("П-CL")
    task = make_task(project=board)
    response = _claim(TD, task.pk)
    assert response.status_code == 403
    assert response.json()["code"] == "task_claim_forbidden"


def test_director_cannot_claim(org):
    task = make_task(department_id=org.ops.id)
    assert _claim(OD, task.pk).status_code == 403


def test_claim_forbidden_via_origin_link(org):
    from apps.tasks.models import DepartmentLinkKind
    task = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    assert _claim(EMP_IT, task.pk).status_code == 403


def test_invisible_task_is_404(org):
    task = make_task(department_id=org.ops.id)
    assert _claim(EMP_IT, task.pk).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_two_claims_one_primary():
    """Два одновременных «Взять в работу» — ровно один основной исполнитель:
    задача блокируется отдельным ``select_for_update`` до проверки «свободна»."""
    org = make_org()
    task = make_task(department_id=org.it.id, status=Status.TODO)
    results: list[int] = []

    def run():
        try:
            results.append(_claim(EMP_IT, task.pk).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [200, 409]
    assert TaskAssignee.objects.filter(task=task).count() == 1
    assert Task.objects.get(pk=task.pk).assignee_id == EMP_IT
