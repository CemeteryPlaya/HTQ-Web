"""Видимость задач по поддереву отдела и для директоров (канбан K1.4).

Мастер-план канбан-досок §5.2, спека этапа 1 §K1.3: сотрудник видит все
задачи своего отдела и подотделов, включая взятые в работу; глава — задачи
поддерева каждого управляемого отдела; ОД и ГД — все задачи отделов и
связанных досок проектов; держатели «Доски задач проекта» — задачи досок.
Задача без проекта, отдела и связей видна только участникам и администратору.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import assign
from apps.hr.models import Department
from apps.tasks.models import DepartmentLinkKind, Status, TaskDepartmentLink

from .helpers import BASE, COMPANY, patch_json
from .org_fixtures import (EMP_DEV, EMP_IT, FIRED, GD, HEAD_IT, OD, OUTSIDER, PM, TD,
                           as_user, make_board, make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _sees(user_id: int, task) -> bool:
    response = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(user_id))
    assert response.status_code in (200, 404), response.content
    return response.status_code == 200


def _listed(user_id: int) -> set[int]:
    response = Client().get(f"{BASE}/tasks/?limit=200", **as_user(user_id))
    assert response.status_code == 200, response.content
    return {row["id"] for row in response.json()}


def test_dept_member_sees_subdept_task_in_progress(org):
    task = make_task(department_id=org.dev.id, status=Status.IN_PROGRESS,
                     assignee_id=EMP_DEV)
    assert _sees(EMP_IT, task)
    assert task.pk in _listed(EMP_IT)
    comments = Client().get(f"{BASE}/tasks/{task.pk}/comments/", **as_user(EMP_IT))
    assert comments.status_code == 200


def test_subdept_member_does_not_see_parent_task(org):
    task = make_task(department_id=org.it.id, status=Status.TODO)
    assert not _sees(EMP_DEV, task)
    assert task.pk not in _listed(EMP_DEV)


def test_prefix_is_not_a_subtree(org):
    task = make_task(department_id=org.itops.id)
    assert not _sees(EMP_IT, task)


def test_member_and_origin_links_give_visibility(org):
    member = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=member, department_id=org.dev.id)
    origin = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=origin, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)
    assert _sees(EMP_IT, member)
    assert _sees(EMP_IT, origin)
    assert not _sees(EMP_DEV, origin)


def test_head_sees_managed_subtree_from_other_dept(org):
    """Глава ``it`` числится в ``hq`` — видит поддерево ``it``, а не ``hq``."""
    sub = make_task(department_id=org.dev.id, assignee_id=EMP_DEV,
                    status=Status.IN_PROGRESS)
    other = make_task(department_id=org.ops.id)
    assert _sees(HEAD_IT, sub)
    assert not _sees(HEAD_IT, other)


@pytest.mark.parametrize("director", [OD, GD])
def test_directors_see_every_department_and_linked_board_task(org, director):
    in_ops = make_task(department_id=org.ops.id, assignee_id=OUTSIDER,
                       status=Status.IN_PROGRESS)
    # Отдел только связью, без основного: «все отделы» видят и такую задачу.
    linked_only = make_task()
    TaskDepartmentLink.objects.create(task=linked_only, department_id=org.itops.id)
    board = make_board("П-K1")
    on_board = make_task(project=board)
    assert _sees(director, in_ops)
    assert _sees(director, linked_only)
    assert _sees(director, on_board)


def test_td_sees_all_linked_board_tasks(org):
    board = make_board("П-K2")
    task = make_task(project=board, assignee_id=OUTSIDER)
    assert _sees(TD, task)
    assert not _sees(TD, make_task(department_id=org.ops.id))


def test_pm_sees_only_own_project_boards(org):
    mine = make_board("П-K3", members=(PM,))
    theirs = make_board("П-K4")
    assert _sees(PM, make_task(project=mine))
    assert not _sees(PM, make_task(project=theirs))


def test_unlinked_board_task_not_opened_by_project_board(org):
    from apps.tasks.models import Project as Board
    plain = Board.objects.create(name="Доска без «Проекта»")
    assert not _sees(OD, make_task(project=plain))


@pytest.mark.parametrize("viewer", [OD, GD, TD, PM, HEAD_IT, EMP_IT])
@pytest.mark.parametrize("path", ["", "comments/", "activity/"])
def test_private_task_hidden(org, viewer, path):
    private = make_task(reporter_id=OUTSIDER, assignee_id=OUTSIDER)
    response = Client().get(f"{BASE}/tasks/{private.pk}/{path}", **as_user(viewer))
    assert response.status_code == 404
    assert private.pk not in _listed(viewer)


def test_elevated_sees_private_task(org):
    from .helpers import admin_token, auth
    private = make_task(reporter_id=OUTSIDER)
    response = Client().get(f"{BASE}/tasks/{private.pk}/", **auth(admin_token()))
    assert response.status_code == 200


def test_fired_employee_has_no_department(org):
    task = make_task(department_id=org.it.id)
    assert not _sees(FIRED, task)


def test_own_department_unknown_to_hr_still_counts(org, monkeypatch):
    """Отдел сотрудника, которого нет в ``hr`` (строку удалили, мок), всё равно
    его — иначе видимость молча сузилась бы до пустой (S1-22)."""
    from apps.hr import interface as hr

    real = hr.get_employee_brief

    def brief(user_id, **kwargs):
        if user_id == OUTSIDER:
            return {"id": 1, "full_name": "x", "department_id": 987654,
                    "position_id": None, "status": "active"}
        return real(user_id, **kwargs)

    monkeypatch.setattr(hr, "get_employee_brief", brief)
    assert _sees(OUTSIDER, make_task(department_id=987654))


def test_hr_disabled_narrows_to_participation(org, monkeypatch):
    from apps.core import services as core_services

    real = core_services.service_status
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено") if name == "hr" else real(name))
    own = make_task(department_id=org.it.id, assignee_id=EMP_IT)
    colleague = make_task(department_id=org.it.id, assignee_id=EMP_DEV)
    assert _sees(EMP_IT, own)
    assert not _sees(EMP_IT, colleague)


SUBRESOURCES = ["transitions/", "comments/", "attachments/", "activity/",
                "volumes/", "daily-reports/"]


@pytest.mark.parametrize("suffix", SUBRESOURCES)
def test_subresources_follow_subtree(org, suffix):
    task = make_task(department_id=org.it.id)
    ok = Client().get(f"{BASE}/tasks/{task.pk}/{suffix}", **as_user(EMP_IT))
    hidden = Client().get(f"{BASE}/tasks/{task.pk}/{suffix}", **as_user(EMP_DEV))
    assert ok.status_code == 200, ok.content
    assert hidden.status_code == 404


def test_real_bpp_gd_role_reads_department_task(org):
    """Настоящая роль ``bpp-gd`` из миграций (строки access/0028), не
    синтетическая роль ``assign`` — видит задачу отдела, правка 403."""
    from apps.hr.models import Position

    from .org_fixtures import _employee

    user = 7711
    _employee(user, org.hq, Position.objects.get(title="Сотрудник (канбан-тест)"))
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user,
                                  role=Role.objects.get(code="bpp-gd"),
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assign(COMPANY, user, "tasks", "read")
    task = make_task(department_id=org.ops.id)
    assert _sees(user, task)
    edit = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"summary": "x"},
                      **as_user(user))
    assert edit.status_code == 403


def test_list_queries_do_not_grow_with_subtree(org):
    """Число запросов списка не зависит от размера поддерева отдела."""
    client = Client()
    for i in range(3):
        make_task(department_id=org.dev.id)
        make_task(department_id=org.it.id)
    client.get(f"{BASE}/tasks/?limit=50", **as_user(EMP_IT))          # разогрев
    with CaptureQueriesContext(connection) as small:
        client.get(f"{BASE}/tasks/?limit=50", **as_user(EMP_IT))
    for i in range(4):
        Department.objects.create(name=f"Подотдел {i}", path=f"kb_it.extra{i}")
    with CaptureQueriesContext(connection) as large:
        client.get(f"{BASE}/tasks/?limit=50", **as_user(EMP_IT))
    # Рубильник сервисов кэшируется на 5 с: истечёт между запросами — у
    # одного из них будет лишний запрос к ServiceStatus, к поддереву не
    # относящийся. Его не считаем.
    assert _counted(large) <= _counted(small)


def _counted(context) -> int:
    return sum(1 for q in context.captured_queries if "core_service_status" not in q["sql"])


def test_scope_built_once_per_request(org, monkeypatch):
    from apps.hr import interface as hr

    calls = {"n": 0}
    real = hr.managed_department_ids

    def counted(user_id):
        calls["n"] += 1
        return real(user_id)

    monkeypatch.setattr(hr, "managed_department_ids", counted)
    task = make_task(department_id=org.it.id, reporter_id=EMP_IT)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"summary": "y"},
                          **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    assert calls["n"] == 1


# ── доски проектов и роудмапы по поддереву (S1-23) ───────────────────────

def test_parent_member_sees_subdept_project_board(org):
    board = make_board("П-K5", department=org.dev)
    response = Client().get(f"{BASE}/projects/{board.pk}/", **as_user(EMP_IT))
    assert response.status_code == 200


def test_holder_opens_roadmap_tasks(org):
    from apps.tasks.models import Roadmap, Site, SiteBlock
    board = make_board("П-K6")
    block = SiteBlock.objects.create(site=Site.objects.create(name="Объект K6", code="K6"),
                                     name="Блок 1")
    roadmap = Roadmap.objects.create(project=board, site_block=block, name="Каркас")
    task = make_task(project=board, roadmap=roadmap)
    response = Client().get(f"{BASE}/roadmaps/{roadmap.pk}/tasks/", **as_user(TD))
    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()] == [task.pk]
