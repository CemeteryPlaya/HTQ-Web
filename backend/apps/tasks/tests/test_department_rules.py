"""Отдел задачи, автор, начальный статус, родитель (канбан K1.5).

Спека этапа 1 §K1.4: рядовой ставит отдел только из своего поддерева (403),
глава — любой при создании (отдел-отправитель — связь ``origin``) и только
внутри управляемых поддеревьев при правке (422: для этого есть перенос);
сначала существование и активность отдела (выключенный ``hr`` — 503 раньше
403). Автор с клиента — только администратору; начальный статус рядового —
``backlog``/``todo``; родитель — только видимая задача; в ``department_ids``
ответа — только отделы-участники (S1-19…S1-21, S1-18, S1-20).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.hr.models import Department
from apps.tasks.models import DepartmentLinkKind, TaskActivity, TaskDepartmentLink

from .helpers import BASE, admin_token, auth, patch_json, post_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, OUTSIDER, as_user, make_org,
                           make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _create(user_id, **body):
    return post_json(Client(), f"{BASE}/tasks/", {"summary": "Новая", **body},
                     **as_user(user_id))


def _patch(user_id, task, **body):
    return patch_json(Client(), f"{BASE}/tasks/{task.pk}/", body, **as_user(user_id))


def _code(response):
    return response.json().get("code")


def _links(task_id) -> set[tuple[int, str]]:
    return set(TaskDepartmentLink.objects.filter(task_id=task_id)
               .values_list("department_id", "kind"))


# ── создание ──────────────────────────────────────────────────────────────

def test_member_creates_in_own_subtree_or_without_department(org):
    assert _create(EMP_DEV, department_id=org.dev.id).status_code == 201
    assert _create(EMP_DEV).status_code == 201


def test_member_cannot_create_in_parent_or_foreign_department(org):
    for department in (org.it, org.ops):
        response = _create(EMP_DEV, department_id=department.id)
        assert response.status_code == 403, response.content
        assert _code(response) == "task_department_forbidden"


def test_department_ids_with_one_foreign_is_forbidden(org):
    response = _create(EMP_IT, department_ids=[org.dev.id, org.ops.id])
    assert response.status_code == 403
    assert _code(response) == "task_department_forbidden"


def test_inactive_department_is_rejected(org):
    old = Department.objects.create(name="Закрытый (канбан)", path="kb_it.old",
                                    is_active=False)
    response = _create(EMP_IT, department_id=old.id)
    assert response.status_code == 422
    assert _code(response) == "task_department_inactive"


def test_head_creates_in_foreign_department_with_origin_link(org):
    response = _create(HEAD_IT, department_id=org.ops.id)
    assert response.status_code == 201, response.content
    body = response.json()
    assert _links(body["id"]) == {(org.ops.id, "member"), (org.it.id, "origin")}
    assert body["reporter_id"] == HEAD_IT                # S1-16: автор — глава
    assert body["department_ids"] == [org.ops.id]        # S1-20: без origin


def test_head_creating_in_foreign_department_cannot_assign(org):
    response = _create(HEAD_IT, department_id=org.ops.id, assignee_id=OUTSIDER)
    assert response.status_code == 422
    assert _code(response) == "task_transfer_assignees"


def test_reporter_from_client_only_for_elevated(org):
    mine = _create(EMP_IT, reporter_id=OUTSIDER).json()
    assert mine["reporter_id"] == EMP_IT
    admin = post_json(Client(), f"{BASE}/tasks/",
                      {"summary": "A", "reporter_id": OUTSIDER}, **auth(admin_token()))
    assert admin.json()["reporter_id"] == OUTSIDER


def test_initial_status_for_member_is_backlog_or_todo(org):
    assert _create(EMP_IT, status="backlog").status_code == 201
    response = _create(EMP_IT, status="in_progress")
    assert response.status_code == 422
    assert _code(response) == "task_status_initial"
    admin = post_json(Client(), f"{BASE}/tasks/", {"summary": "A", "status": "done"},
                      **auth(admin_token()))
    assert admin.status_code == 201


def test_parent_must_be_visible(org):
    private = make_task(reporter_id=OUTSIDER)
    assert _create(EMP_IT, parent_id=private.pk).status_code == 404
    mine = make_task(reporter_id=EMP_IT)
    assert _patch(EMP_IT, mine, parent_id=private.pk).status_code == 404
    visible = make_task(department_id=org.it.id)
    assert _patch(EMP_IT, mine, parent_id=visible.pk).status_code == 200


def test_hr_disabled_with_department_is_503_before_403(org, monkeypatch):
    from apps.core import services as core_services

    real = core_services.service_status
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено") if name == "hr" else real(name))
    response = _create(EMP_DEV, department_id=org.ops.id)
    assert response.status_code == 503
    assert _create(EMP_DEV).status_code == 201


# ── правка ────────────────────────────────────────────────────────────────

def test_member_patch_out_of_subtree_is_forbidden(org):
    task = make_task(department_id=org.dev.id, reporter_id=EMP_DEV)
    response = _patch(EMP_DEV, task, department_id=org.it.id)
    assert response.status_code == 403
    assert _code(response) == "task_department_forbidden"


def test_head_patch_within_managed_subtree(org):
    task = make_task(department_id=org.dev.id)
    assert _patch(HEAD_IT, task, department_id=org.it.id).status_code == 200


def test_head_patch_to_foreign_department_needs_transfer(org):
    task = make_task(department_id=org.it.id)
    response = _patch(HEAD_IT, task, department_id=org.ops.id)
    assert response.status_code == 422
    assert _code(response) == "task_department_use_transfer"


def test_head_patch_into_own_seat_department_needs_transfer(org):
    """Глава ``it`` числится в ``hq`` — увести задачу ``it.dev`` в ``hq``
    правкой нельзя: это перенос (S1-19)."""
    task = make_task(department_id=org.dev.id)
    response = _patch(HEAD_IT, task, department_id=org.hq.id)
    assert response.status_code == 422
    assert _code(response) == "task_department_use_transfer"


def test_department_ids_only_realign_is_checked(org):
    task = make_task(department_id=org.it.id)
    response = _patch(HEAD_IT, task, department_ids=[org.ops.id])
    assert response.status_code == 422
    task.refresh_from_db()
    assert task.department_id == org.it.id


def test_head_cannot_promote_foreign_member_link_to_primary(org):
    """Ревью K1.5: глава создаёт задачу на свой и чужой отдел (можно), затем
    одной правкой делает чужой основным — это перенос, а не правка."""
    created = _create(HEAD_IT, department_ids=[org.it.id, org.ops.id])
    assert created.status_code == 201, created.content
    task_id = created.json()["id"]
    response = patch_json(Client(), f"{BASE}/tasks/{task_id}/",
                          {"department_id": org.ops.id}, **as_user(HEAD_IT))
    assert response.status_code == 422
    assert _code(response) == "task_department_use_transfer"


def test_department_ids_reorder_cannot_promote_foreign_member_to_primary(org):
    """Тот же обход порядком набора: первый отдел ``department_ids`` становится
    основным, поэтому ``[ops, it]`` без ``department_id`` — тоже перенос."""
    created = _create(HEAD_IT, department_ids=[org.it.id, org.ops.id])
    task_id = created.json()["id"]
    response = patch_json(Client(), f"{BASE}/tasks/{task_id}/",
                          {"department_ids": [org.ops.id, org.it.id]}, **as_user(HEAD_IT))
    assert response.status_code == 422
    assert _code(response) == "task_department_use_transfer"


def test_resending_unchanged_department_set_is_allowed(org):
    """Форма шлёт прежний набор целиком — старая чужая связь не мешает."""
    task = make_task(department_id=org.it.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.ops.id)
    response = _patch(HEAD_IT, task, department_id=org.it.id,
                      department_ids=[org.it.id, org.ops.id])
    assert response.status_code == 200, response.content


def test_elevated_patch_any_department(org):
    task = make_task(department_id=org.it.id)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/",
                          {"department_id": org.ops.id}, **auth(admin_token()))
    assert response.status_code == 200


def test_reporter_patch_only_elevated(org):
    task = make_task(department_id=org.it.id, reporter_id=EMP_DEV)
    response = _patch(HEAD_IT, task, reporter_id=HEAD_IT)
    assert response.status_code == 422
    assert _code(response) == "task_reporter_forbidden"
    assert _patch(HEAD_IT, task, reporter_id=EMP_DEV).status_code == 200   # то же значение
    admin = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"reporter_id": HEAD_IT},
                       **auth(admin_token()))
    assert admin.status_code == 200


def test_patch_department_ids_keeps_origin(org):
    task = make_task(department_id=org.dev.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.dev.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.ops.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    assert _patch(HEAD_IT, task, department_ids=[org.it.id, org.dev.id]).status_code == 200
    assert _links(task.pk) == {(org.it.id, "member"), (org.dev.id, "member"),
                               (org.ops.id, "origin")}


def test_origin_in_new_set_becomes_member(org):
    task = make_task(department_id=org.dev.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.dev.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    assert _patch(HEAD_IT, task, department_ids=[org.dev.id, org.it.id]).status_code == 200
    assert _links(task.pk) == {(org.dev.id, "member"), (org.it.id, "member")}


def test_department_change_is_logged(org):
    task = make_task(department_id=org.dev.id)
    assert _patch(HEAD_IT, task, department_id=org.it.id).status_code == 200
    assert TaskActivity.objects.filter(task=task, field_name="department_id",
                                       old_value=str(org.dev.id),
                                       new_value=str(org.it.id)).exists()


def test_response_department_ids_exclude_origin(org):
    task = make_task(department_id=org.ops.id, reporter_id=EMP_IT)
    TaskDepartmentLink.objects.create(task=task, department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=task, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    body = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).json()
    assert body["department_ids"] == [org.ops.id]
    assert [d["id"] for d in body["departments"]] == [org.ops.id]
