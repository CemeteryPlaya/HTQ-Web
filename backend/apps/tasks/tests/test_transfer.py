"""Перенос задачи в другой отдел (канбан K1.6, мастер-план K-08, спека §K1.5).

Глава отдела задачи (или администратор) отправляет её в другой отдел:
исполнители снимаются, статус становится «К выполнению» (даже из «На
проверке» — мимо FSM, S1-06), отдел-отправитель остаётся связью ``origin`` —
видит ход работ, прав и «Взять в работу» не получает; глава отдела-получателя
получает уведомление.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.notifications.models import Notification
from apps.tasks.models import (DepartmentLinkKind, Status, TaskActivity, TaskAssignee,
                               TaskDepartmentLink)

from .helpers import BASE, admin_token, auth, patch_json, post_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, HEAD_OPS, OD, OUTSIDER, as_user,
                           make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _transfer(user_headers, task_id, **body):
    return post_json(Client(), f"{BASE}/tasks/{task_id}/transfer/", body, **user_headers)


def _links(task_id) -> set[tuple[int, str]]:
    return set(TaskDepartmentLink.objects.filter(task_id=task_id)
               .values_list("department_id", "kind"))


def _in_review_task(org):
    task = make_task(department_id=org.dev.id, status=Status.IN_REVIEW,
                     assignee_id=EMP_DEV, reporter_id=EMP_DEV, supervisor_id=EMP_DEV)
    TaskAssignee.objects.create(task=task, user_id=EMP_DEV, role="primary")
    TaskDepartmentLink.objects.create(task=task, department_id=org.dev.id)
    return task


def test_head_transfers_task_in_review(org):
    task = _in_review_task(org)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["department_id"] == org.ops.id
    assert body["status"] == "todo"
    assert body["assignee_id"] is None
    assert body["assignees"] == []
    assert body["reporter_id"] == EMP_DEV and body["supervisor_id"] == EMP_DEV   # S1-16
    assert _links(task.pk) == {(org.ops.id, "member"), (org.dev.id, "origin")}
    fields = set(TaskActivity.objects.filter(task=task).values_list("field_name", flat=True))
    assert {"transfer", "department_id", "assignee_id", "status"} <= fields


def test_transfer_notifies_target_head_who_can_open_it(org):
    task = _in_review_task(org)
    _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id)
    note = Notification.objects.get(recipient_id=HEAD_OPS)
    assert note.title.startswith("В ваш отдел передана задача:")
    assert "event=transfer" in note.url
    assert Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(HEAD_OPS)).status_code == 200


def test_sender_sees_but_cannot_edit_or_claim(org):
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT)
    assert _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id).status_code == 200
    client = Client()
    assert client.get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).status_code == 200
    assert patch_json(client, f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                      **as_user(EMP_IT)).status_code == 403
    claim = post_json(client, f"{BASE}/tasks/{task.pk}/claim/", {}, **as_user(EMP_IT))
    assert claim.status_code == 403
    assert claim.json()["code"] == "task_claim_forbidden"


def test_member_cannot_transfer(org):
    task = make_task(department_id=org.it.id, reporter_id=EMP_IT)
    response = _transfer(as_user(EMP_IT), task.pk, department_id=org.ops.id)
    assert response.status_code == 403
    assert response.json()["code"] == "task_transfer_forbidden"


def test_head_of_other_department_cannot_transfer(org):
    task = make_task(department_id=org.it.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.ops.id)
    response = _transfer(as_user(HEAD_OPS), task.pk, department_id=org.ops.id)
    assert response.status_code == 403


def test_director_cannot_transfer(org):
    task = make_task(department_id=org.it.id)
    assert _transfer(as_user(OD), task.pk, department_id=org.ops.id).status_code == 403


def test_invisible_task_is_404_not_403(org):
    task = make_task(department_id=org.ops.id)
    assert _transfer(as_user(HEAD_IT), task.pk, department_id=org.it.id).status_code == 404


def test_terminal_task_is_not_transferred(org):
    task = make_task(department_id=org.it.id, status=Status.DONE)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id)
    assert response.status_code == 409
    assert response.json()["code"] == "task_transfer_terminal"


def test_same_department_is_rejected(org):
    task = make_task(department_id=org.it.id)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.it.id)
    assert response.status_code == 422
    assert response.json()["code"] == "task_transfer_same"


def test_inactive_target_is_rejected(org):
    from apps.hr.models import Department
    closed = Department.objects.create(name="Закрытый (перенос)", path="kb_closed",
                                       is_active=False)
    task = make_task(department_id=org.it.id)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=closed.id)
    assert response.status_code == 422
    assert response.json()["code"] == "task_department_inactive"


def test_transfer_back_turns_origin_into_member(org):
    task = make_task(department_id=org.it.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id)
    assert _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id).status_code == 200
    assert _transfer(as_user(HEAD_OPS), task.pk, department_id=org.it.id).status_code == 200
    assert _links(task.pk) == {(org.it.id, "member"), (org.ops.id, "origin")}


def test_elevated_without_managed_departments_leaves_no_origin_when_no_department(org):
    task = make_task(reporter_id=OUTSIDER)
    response = _transfer(auth(admin_token()), task.pk, department_id=org.ops.id)
    assert response.status_code == 200, response.content
    assert _links(task.pk) == {(org.ops.id, "member")}


def test_head_transfers_task_without_department(org):
    task = make_task(reporter_id=HEAD_IT)
    assert _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id).status_code == 200
    assert _links(task.pk) == {(org.ops.id, "member"), (org.it.id, "origin")}


def test_sender_outside_managed_is_rejected(org):
    task = make_task(reporter_id=HEAD_IT)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id,
                         sender_department_id=org.hq.id)
    assert response.status_code == 422


def test_extra_body_field_is_rejected(org):
    task = make_task(department_id=org.it.id)
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id,
                         assignee_id=EMP_IT)
    assert response.status_code == 422


def test_hr_off_elevated_transfer_succeeds(org, monkeypatch):
    from apps.core import services as core_services

    real = core_services.service_status
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено") if name == "hr" else real(name))
    task = make_task(department_id=org.it.id)
    response = _transfer(auth(admin_token()), task.pk, department_id=org.ops.id)
    assert response.status_code == 200, response.content


def test_hr_off_head_transfer_is_503(org, monkeypatch):
    """Выключенный hr: проверить цель и право главы нельзя — 503 (S1-05).
    Глава — автор задачи: без hr видимость сужается до участия, и чужую
    задачу отдела он не увидел бы вовсе (404)."""
    from apps.core import services as core_services

    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT)
    real = core_services.service_status
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено") if name == "hr" else real(name))
    response = _transfer(as_user(HEAD_IT), task.pk, department_id=org.ops.id)
    assert response.status_code == 503
