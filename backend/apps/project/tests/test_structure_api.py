"""Ручки проектной структуры (спек 2026-10-06 §3–§4): кто видит и кто правит,
коды ошибок, все пути."""

import json
from datetime import date

import pytest
from django.test import Client

from apps.access.tests.helpers import assign, token
from apps.hr.models import Department, Employee, Position
from apps.project.models import ProjectRole
from apps.project.services import projects

BASE = "/api/project/v1"
MANAGER, EDITOR, MEMBER, OUTSIDER, ROLES_EDITOR = 11, 7, 21, 31, 41


def _auth(slug, user_id):
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def _send(method, slug, user_id, url, body=None):
    client = Client()
    call = getattr(client, method)
    kwargs = _auth(slug, user_id)
    if body is not None:
        return call(f"{BASE}/{url}", data=json.dumps(body), content_type="application/json",
                    **kwargs)
    return call(f"{BASE}/{url}", **kwargs)


@pytest.fixture
def env(company_context):
    slug = company_context["slug"]
    # ПМ-подобный руководитель: модуль project на запись (участники), без узла структуры.
    assign(slug, MANAGER, "project.members", "edit")
    assign(slug, EDITOR, "project.structure", "edit")
    assign(slug, MEMBER, "project.projects", "read")
    assign(slug, OUTSIDER, "project.projects", "read")
    assign(slug, ROLES_EDITOR, "project.roles", "edit")
    own = projects.create(code="П-300", name="Свой", country_code="KZ", actor_id=1,
                          manager_user_id=MANAGER)
    projects.add_member(own, MEMBER, actor_id=1)
    foreign = projects.create(code="П-301", name="Чужой", country_code="KZ", actor_id=1,
                              manager_user_id=99)
    roles = {level: ProjectRole.objects.create(name=f"Т-L{level}", level=level)
             for level in (1, 2, 3, 4)}
    department = Department.objects.create(name="Стройка", path="stroy")
    position = Position.objects.create(title="Инженер", department=department, weight=10)
    worker = Employee.objects.create(last_name="Сидоров", first_name="Олег",
                                     email="w@htq.test", department=department,
                                     position=position, hire_date=date(2024, 1, 9))
    return {"slug": slug, "own": str(own.id), "foreign": str(foreign.id), "roles": roles,
            "worker": worker}


def _top(env, user_id=MANAGER, project="own"):
    return _send("post", env["slug"], user_id, f"projects/{env[project]}/slots",
                 {"role_id": env["roles"][1].id})


@pytest.mark.django_db
def test_manager_edits_own_project_only(env):
    """Review Focus 1: руководитель без узла — свой проект да, чужой нет."""
    created = _top(env)
    assert created.status_code == 201, created.content
    assert _top(env, project="foreign").status_code == 404  # чужой не виден вовсе
    assign(env["slug"], MANAGER, "project.all", "view")
    refused = _top(env, project="foreign")
    assert refused.status_code == 403 and refused.json()["code"] == "E-ACC-01"


@pytest.mark.django_db
def test_structure_holder_sees_and_edits_any_project(env):
    """Review Focus 2: держатель project.structure без project.all видит любой."""
    assert _send("get", env["slug"], EDITOR, f"projects/{env['foreign']}").status_code == 200
    assert _top(env, user_id=EDITOR, project="foreign").status_code == 201
    listed = _send("get", env["slug"], EDITOR, "projects").json()
    assert {p["code"] for p in listed} == {"П-300", "П-301"}


@pytest.mark.django_db
def test_member_reads_but_cannot_write_and_outsider_gets_404(env):
    _top(env)
    read = _send("get", env["slug"], MEMBER, f"projects/{env['own']}/structure")
    assert read.status_code == 200 and read.json()["can_edit"] is False
    assert len(read.json()["slots"]) == 1
    assert _top(env, user_id=MEMBER).status_code == 403
    assert _send("get", env["slug"], OUTSIDER,
                 f"projects/{env['own']}/structure").status_code == 404


@pytest.mark.django_db
def test_full_flow_and_error_codes(env):
    slug, own = env["slug"], env["own"]
    top = _top(env).json()["id"]
    bad = _send("post", slug, MANAGER, f"projects/{own}/slots",
                {"role_id": env["roles"][2].id})
    assert bad.status_code == 409 and bad.json()["code"] == "E-PRJ-05"
    crew = _send("post", slug, MANAGER, f"projects/{own}/slots",
                 {"role_id": env["roles"][4].id, "parent_id": top, "planned_headcount": 3,
                  "title": "бригада 1"})
    assert crew.status_code == 201
    crew_id = crew.json()["id"]

    placed = _send("post", slug, MANAGER, f"slots/{crew_id}/assignments",
                   {"employee_id": env["worker"].id, "date_from": "2026-01-01"})
    assert placed.status_code == 201
    missing = _send("post", slug, MANAGER, f"slots/{crew_id}/assignments",
                    {"employee_id": 999999, "date_from": "2026-01-01"})
    assert missing.status_code == 422 and missing.json()["code"] == "E-PRJ-06"

    body = _send("get", slug, MANAGER, f"projects/{own}/structure?on=2026-02-01").json()
    assert body["can_edit"] is True and body["on"] == "2026-02-01"
    slot = next(s for s in body["slots"] if s["id"] == crew_id)
    assert slot["parent_id"] == top and slot["actual_headcount"] == 1
    assert slot["assignments"][0]["full_name"] == "Сидоров Олег"

    assignment = placed.json()["id"]
    ended = _send("patch", slug, MANAGER, f"assignments/{assignment}",
                  {"date_to": "2026-01-31"})
    assert ended.status_code == 200
    assert _send("delete", slug, MANAGER, f"assignments/{assignment}").status_code == 409
    closed = _send("patch", slug, MANAGER, f"slots/{crew_id}", {"closed_on": "2026-02-01"})
    assert closed.status_code == 200
    after = _send("get", slug, MANAGER, f"projects/{own}/structure?on=2026-03-01").json()
    assert [s["id"] for s in after["slots"]] == [top]
    assert _send("get", slug, MANAGER,
                 f"projects/{own}/structure?on=вчера").status_code == 422


@pytest.mark.django_db
def test_roles_catalog_rights(env):
    slug = env["slug"]
    listed = _send("get", slug, MEMBER, "project-roles").json()
    assert [r["name"] for r in listed if r["name"].startswith("Т-")] == [
        "Т-L1", "Т-L2", "Т-L3", "Т-L4"]
    body = {"name": "Прораб", "level": 3, "default_part": "site"}
    assert _send("post", slug, MANAGER, "project-roles", body).status_code == 403
    made = _send("post", slug, ROLES_EDITOR, "project-roles", body)
    assert made.status_code == 201 and made.json()["default_part"] == "site"
    twice = _send("post", slug, ROLES_EDITOR, "project-roles", body)
    assert twice.status_code == 409 and twice.json()["code"] == "E-PRJ-07"
    role_id = made.json()["id"]
    assert _send("patch", slug, ROLES_EDITOR, f"project-roles/{role_id}",
                 {"is_active": False}).json()["is_active"] is False
    assert _send("delete", slug, ROLES_EDITOR, f"project-roles/{role_id}").status_code == 204
    _top(env)
    used = _send("delete", slug, ROLES_EDITOR, f"project-roles/{env['roles'][1].id}")
    assert used.status_code == 409 and used.json()["code"] == "E-PRJ-07"


@pytest.mark.django_db
def test_employee_search_is_for_structure_editors_only(env):
    slug = env["slug"]
    assert _send("get", slug, MEMBER, "employees?q=Сид").status_code == 403
    found = _send("get", slug, MANAGER, "employees?q=Сид")
    assert found.status_code == 200
    assert found.json() == [{"id": env["worker"].id, "full_name": "Сидоров Олег",
                             "position_title": "Инженер"}]
    assert _send("get", slug, EDITOR, "employees?q=").json() == []
