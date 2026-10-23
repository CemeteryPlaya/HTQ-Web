"""Запросы доступа к задаче (решения K-31, K-32; мастер-план канбана §3.5,
§6.2; этап S2).

Кто видит задачу, но не в роли, просит «на исполнение» или «на владение».
Решающие зависят от вида; первый решивший закрывает запрос, второй получает
409 с тем, кто решил. Одобрение «исполнения» делает запросившего основным
исполнителем вместо прежнего; «владения» — руководителем (с заменой) или
делегатом. Решающим — плашка и счётчик в карточке, панель «Запросы»; главе —
история отдела.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.notifications.models import Notification
from apps.tasks.models import (AccessRequestStatus, Status, TaskAccessRequest, TaskActivity,
                               TaskAssignee, TaskDelegate)

from .helpers import BASE, admin_token, auth, post_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, OD, OUTSIDER, TD, as_user, make_org,
                           make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _it_task(org):
    """Задача отдела it: автор и руководитель TD, исполнитель EMP_DEV, глава
    отдела HEAD_IT. EMP_IT её видит (свой отдел), но в ней не участвует."""
    task = make_task(department_id=org.it.id, reporter_id=TD, supervisor_id=TD,
                     assignee_id=EMP_DEV, status=Status.TODO)
    TaskAssignee.objects.create(task=task, user_id=EMP_DEV, role="primary")
    return task


def _request(task, kind, who=EMP_IT, comment=""):
    return post_json(Client(), f"{BASE}/tasks/{task.pk}/access-requests",
                     {"kind": kind, "comment": comment}, **as_user(who))


def _approve(request_id, who, **body):
    return post_json(Client(), f"{BASE}/access-requests/{request_id}/approve", body,
                     **as_user(who))


def test_execute_request_replaces_the_primary(org):
    task = _it_task(org)
    assert _request(task, "execute", who=OUTSIDER).status_code == 404     # задачу не видит
    response = _request(task, "execute", comment="Возьму, у меня есть время")
    assert response.status_code == 201, response.content
    row = response.json()
    assert row["status"] == "pending" and row["requester"]["id"] == EMP_IT
    # Решающим «исполнения» (руководитель/автор TD, исполнитель EMP_DEV, глава
    # HEAD_IT) — адресное уведомление со ссылкой на панель запросов.
    notified = set(Notification.objects.filter(url__contains="event=access_requested")
                   .values_list("recipient_id", flat=True))
    assert notified == {TD, EMP_DEV, HEAD_IT}
    again = _request(task, "execute")
    assert again.status_code == 409 and again.json()["code"] == "task_access_pending"

    approved = _approve(row["id"], who=EMP_DEV)
    assert approved.status_code == 200, approved.content
    body = approved.json()
    assert body["status"] == "approved" and body["approve_mode"] == "replace"
    assert body["replaced"]["id"] == EMP_DEV
    task.refresh_from_db()
    assert task.assignee_id == EMP_IT
    assert list(TaskAssignee.objects.filter(task=task).values_list("user_id", "role")) == [
        (EMP_IT, "primary")]
    fields = set(TaskActivity.objects.filter(task=task).values_list("field_name", flat=True))
    assert {"access_requested", "access_approved", "assignee_id"} <= fields

    second = _approve(row["id"], who=TD)
    assert second.status_code == 409
    assert second.json()["code"] == "task_access_decided"
    assert second.json()["details"]["decided_by"]["id"] == EMP_DEV


def test_execute_approval_rejects_delegate_mode(org):
    task = _it_task(org)
    row = _request(task, "execute").json()
    response = _approve(row["id"], who=TD, mode="delegate")
    assert response.status_code == 422 and response.json()["code"] == "task_access_mode"


def test_own_request_needs_mode_and_supports_both(org):
    task = _it_task(org)
    row = _request(task, "own").json()
    missing = _approve(row["id"], who=TD)
    assert missing.status_code == 422 and missing.json()["code"] == "task_access_mode"
    # Исполнитель EMP_DEV «владение» не решает — только руководитель и глава.
    forbidden = _approve(row["id"], who=EMP_DEV, mode="replace")
    assert forbidden.status_code == 403 and forbidden.json()["code"] == "task_access_forbidden"
    approved = _approve(row["id"], who=HEAD_IT, mode="replace")
    assert approved.status_code == 200, approved.content
    task.refresh_from_db()
    assert task.supervisor_id == EMP_IT
    assert approved.json()["replaced"]["id"] == TD
    replaced_note = Notification.objects.filter(recipient_id=TD, title__startswith="Замена")
    assert replaced_note.exists()

    other = _it_task(org)
    row = _request(other, "own").json()
    approved = _approve(row["id"], who=TD, mode="delegate")
    assert approved.status_code == 200
    other.refresh_from_db()
    assert other.supervisor_id == TD
    assert TaskDelegate.objects.filter(task=other, user_id=EMP_IT).exists()


def test_reject_cancel_and_already_in_role(org):
    task = _it_task(org)
    row = _request(task, "execute").json()
    rejected = post_json(Client(), f"{BASE}/access-requests/{row['id']}/reject",
                         {"comment": "Уже в работе у коллеги"}, **as_user(TD))
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert Notification.objects.filter(recipient_id=EMP_IT,
                                       title__contains="отклонён").exists()

    row = _request(task, "own").json()
    url = f"{BASE}/access-requests/{row['id']}"
    assert Client().delete(url, **as_user(TD)).status_code == 403
    assert Client().delete(url, **as_user(EMP_IT)).status_code == 204
    assert TaskAccessRequest.objects.get(pk=row["id"]).status == AccessRequestStatus.CANCELLED

    # Исполнитель «на исполнение» уже в роли.
    already = _request(task, "execute", who=EMP_DEV)
    assert already.status_code == 409 and already.json()["code"] == "task_access_already"


def test_viewer_without_role_cannot_decide(org):
    task = _it_task(org)
    row = _request(task, "execute").json()
    # ОД видит все отделы, но к задаче отношения не имеет.
    response = _approve(row["id"], who=OD)
    assert response.status_code == 403


def test_nobody_to_decide_falls_back_to_the_admin(org):
    task = make_task(reporter_id=EMP_IT, status=Status.TODO)      # без отдела и руководителя
    row = _request(task, "own").json()
    assert _approve(row["id"], who=EMP_IT, mode="replace").status_code == 403
    response = post_json(Client(), f"{BASE}/access-requests/{row['id']}/approve",
                         {"mode": "replace"}, **auth(admin_token()))
    assert response.status_code == 200, response.content


def test_card_flags_inbox_and_task_list(org):
    task = _it_task(org)
    detail = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).json()
    assert detail["can"]["request_access"] == ["execute", "own"]
    assert detail["can"]["decide_access"] is False
    _request(task, "execute")
    detail = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).json()
    assert detail["can"]["request_access"] == ["own"]
    lead = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(TD)).json()
    assert lead["can"]["decide_access"] is True and lead["pending_access_requests"] == 1

    inbox = Client().get(f"{BASE}/access-requests/inbox", **as_user(TD)).json()
    assert inbox["to_decide_count"] == 1 and inbox["to_decide"][0]["task"]["id"] == task.pk
    mine = Client().get(f"{BASE}/access-requests/inbox", **as_user(EMP_IT)).json()
    assert mine["to_decide_count"] == 0 and len(mine["mine"]) == 1

    # Решающему — все запросы задачи, остальным — только свои.
    assert len(Client().get(f"{BASE}/tasks/{task.pk}/access-requests",
                            **as_user(TD)).json()) == 1
    assert Client().get(f"{BASE}/tasks/{task.pk}/access-requests",
                        **as_user(OD)).json() == []


def test_department_history_for_the_head(org):
    task = _it_task(org)
    row = _request(task, "own").json()
    _approve(row["id"], who=TD, mode="replace")
    url = f"{BASE}/boards/departments/{org.it.id}/access-history"
    assert Client().get(url, **as_user(EMP_IT)).status_code == 404
    body = Client().get(url, **as_user(HEAD_IT)).json()
    kinds = [item["type"] for item in body["items"]]
    assert kinds.count("request") == 1 and kinds.count("transfer") == 1
    transfer = next(item for item in body["items"] if item["type"] == "transfer")
    assert transfer["from"]["id"] == TD and transfer["to"]["id"] == EMP_IT
    only_requests = Client().get(url, {"kind": "own"}, **as_user(HEAD_IT)).json()
    assert [item["type"] for item in only_requests["items"]] == ["request"]
