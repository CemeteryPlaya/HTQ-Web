"""Права главы отдела на задачи своего поддерева (канбан K1.4, K-06).

Глава (``Department.manager``) правит, переставляет и удаляет задачи
поддерева управляемого отдела, не будучи их участником, — для ``can_edit``
он равен руководителю задачи, в том числе добавляет и снимает делегатов
(S1-24). Связь ``origin`` прав не даёт (S1-03). ОД и ГД только читают и
комментируют.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import DepartmentLinkKind, Status, TaskDepartmentLink

from .helpers import BASE, patch_json, post_json
from .org_fixtures import (EMP_DEV, GD, HEAD_IT, OD, OUTSIDER, as_user, make_org,
                           make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def test_head_edits_subdept_task_without_participation(org):
    task = make_task(department_id=org.dev.id, assignee_id=EMP_DEV,
                     status=Status.TODO, reporter_id=EMP_DEV)
    client = Client()
    me = as_user(HEAD_IT)
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/", {"summary": "Новое"},
                      **me).status_code == 200
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/supervisor/",
                      {"user_id": EMP_DEV}, **me).status_code == 200
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/assignees/",
                      {"assignees": [{"user_id": EMP_DEV, "role": "primary"}]},
                      **me).status_code == 200
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/progress/", {"percent": 40},
                      **me).status_code == 200
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/", {"status": "in_progress"},
                      **me).status_code == 200
    assert client.delete(f"{BASE}/tasks/{task.pk}/", **me).status_code == 204


def test_head_adds_and_removes_delegate(org):
    task = make_task(department_id=org.it.id, supervisor_id=EMP_DEV)
    client = Client()
    added = post_json(client, f"{BASE}/tasks/{task.pk}/delegates/",
                      {"user_id": OUTSIDER}, **as_user(HEAD_IT))
    assert added.status_code == 201, added.content
    removed = client.delete(f"{BASE}/tasks/{task.pk}/delegates/{OUTSIDER}/",
                            **as_user(HEAD_IT))
    assert removed.status_code == 200, removed.content


def test_head_cannot_touch_other_dept_task(org):
    task = make_task(department_id=org.ops.id)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                          **as_user(HEAD_IT))
    assert response.status_code == 404


def test_origin_link_gives_no_rights(org):
    task = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    client = Client()
    assert client.get(f"{BASE}/tasks/{task.pk}/", **as_user(HEAD_IT)).status_code == 200
    response = patch_json(client, f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                          **as_user(HEAD_IT))
    assert response.status_code == 403


def test_member_link_gives_head_rights(org):
    task = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.dev.id)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                          **as_user(HEAD_IT))
    assert response.status_code == 200


@pytest.mark.parametrize("director", [OD, GD])
def test_directors_read_only(org, director):
    task = make_task(department_id=org.ops.id)
    client = Client()
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                      **as_user(director)).status_code == 403
    assert post_json(client, f"{BASE}/tasks/{task.pk}/comments/", {"body": "Как дела?"},
                     **as_user(director)).status_code == 201
