"""Флаги ``can`` карточки и списка совпадают с исходом ручек (канбан K1.6).

Кнопки фронта показываются по ``can``; сервер — единственный источник прав.
Флаг, расходящийся с ручкой, — кнопка, которая отвечает 403, или права без
кнопки. Поэтому для каждой роли флаг сверяется с настоящим вызовом ручки.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import Status

from .helpers import BASE, admin_token, auth, patch_json, post_json
from .org_fixtures import EMP_DEV, EMP_IT, HEAD_IT, OD, OUTSIDER, as_user, make_org, make_task

pytestmark = pytest.mark.django_db

ROLES = {
    "participant": lambda: as_user(EMP_DEV),
    "head": lambda: as_user(HEAD_IT),
    "colleague": lambda: as_user(EMP_IT),
    "director": lambda: as_user(OD),
    "elevated": lambda: auth(admin_token()),
}


@pytest.fixture
def org():
    return make_org()


def _fresh(org):
    return make_task(department_id=org.dev.id, assignee_id=EMP_DEV, status=Status.TODO)


def _can(headers, task):
    response = Client().get(f"{BASE}/tasks/{task.pk}/", **headers)
    assert response.status_code == 200, response.content
    return response.json()["can"]


@pytest.mark.parametrize("role", list(ROLES))
def test_full_edit_flag_matches_patch(org, role):
    task = _fresh(org)
    flag = _can(ROLES[role](), task)["full_edit"]
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                          **ROLES[role]())
    assert flag == (response.status_code == 200), (role, response.status_code)


@pytest.mark.parametrize("role", list(ROLES))
def test_soft_edit_flag_matches_progress(org, role):
    task = _fresh(org)
    flag = _can(ROLES[role](), task)["soft_edit"]
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/progress/", {"percent": 10},
                          **ROLES[role]())
    assert flag == (response.status_code == 200), (role, response.status_code)


@pytest.mark.parametrize("role", list(ROLES))
def test_transfer_flag_matches_transfer(org, role):
    task = _fresh(org)
    flag = _can(ROLES[role](), task)["transfer"]
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/transfer/",
                         {"department_id": org.ops.id}, **ROLES[role]())
    assert flag == (response.status_code == 200), (role, response.status_code)


@pytest.mark.parametrize("role", list(ROLES))
def test_claim_flag_matches_claim(org, role):
    task = make_task(department_id=org.dev.id, status=Status.TODO)
    flag = _can(ROLES[role](), task)["claim"]
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/claim/", {}, **ROLES[role]())
    assert flag == (response.status_code == 200), (role, response.status_code)


def test_comment_flag_is_true_for_viewers(org):
    task = _fresh(org)
    assert _can(as_user(OD), task)["comment"] is True


def test_can_present_in_create_patch_and_transition_responses(org):
    created = post_json(Client(), f"{BASE}/tasks/", {"summary": "C"}, **as_user(EMP_IT))
    assert set(created.json()["can"]) == {"full_edit", "soft_edit", "comment", "transfer",
                                          "claim", "delete", "request_access", "decide_access"}
    task_id = created.json()["id"]
    patched = patch_json(Client(), f"{BASE}/tasks/{task_id}/", {"status": "in_progress"},
                         **as_user(EMP_IT))
    assert patched.json()["can"]["full_edit"] is True


def test_list_claim_flag_matches_claim(org):
    free = make_task(department_id=org.dev.id, status=Status.TODO)
    busy = make_task(department_id=org.dev.id, assignee_id=OUTSIDER)
    rows = {row["id"]: row for row in
            Client().get(f"{BASE}/tasks/?scope=department", **as_user(EMP_IT)).json()}
    assert rows[free.pk]["can"]["claim"] is True
    assert rows[busy.pk]["can"]["claim"] is False


def test_department_links_in_detail(org):
    from apps.tasks.models import DepartmentLinkKind, TaskDepartmentLink
    task = make_task(department_id=org.ops.id, reporter_id=EMP_IT)
    TaskDepartmentLink.objects.create(task=task, department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    body = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).json()
    assert {(d["department_id"], d["kind"]) for d in body["department_links"]} == {
        (org.ops.id, "member"), (org.it.id, "origin")}
    assert all(d["name"] for d in body["department_links"])
