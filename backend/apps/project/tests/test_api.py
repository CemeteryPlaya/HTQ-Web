"""Ручки проектов: создают директора и администраторы (узел project.projects),
участников ведут ПМ и HR (узел project.members), ПМ видит свои проекты."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import assign, token

BASE = "/api/project/v1"


def _auth(slug, user_id=7):
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def _create(slug, **body):
    payload = {"code": "П-015", "name": "Объект 15", "country_code": "KZ",
               "manager_user_id": 11, **body}
    return Client().post(f"{BASE}/projects", data=json.dumps(payload),
                         content_type="application/json", **_auth(slug))


@pytest.mark.django_db
def test_create_needs_write(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project", "view")
    assert _create(slug).status_code == 403
    assign(slug, 7, "project.projects", "full")
    response = _create(slug)
    assert response.status_code == 201, response.content
    assert response.json()["code"] == "П-015"


@pytest.mark.django_db
def test_duplicate_code_is_422(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    _create(slug)
    second = _create(slug)
    assert second.status_code == 422 and second.json()["code"] == "E-PRJ-01"


@pytest.mark.django_db
def test_reversed_dates_are_refused(company_context):
    """Сроки «Проекта» проверяет он сам: доска задач их повторяет и не
    спорит с ними (D-02, решение 01.10)."""
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    response = _create(slug, date_start="2026-05-01", date_end="2026-04-01")
    assert response.status_code == 422 and response.json()["code"] == "E-VAL-01"
    assert response.json()["fields"] == [{"field": "date_end", "message": "Раньше даты начала"}]
    assert _create(slug, date_start="2026-04-01", date_end="2026-04-01").status_code == 201


@pytest.mark.django_db
def test_members(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.members", "full")
    # Директор: видит все проекты, а не только те, где участник.
    assign(slug, 7, "project.all", "view")
    project_id = _create(slug).json()["id"]
    url = f"{BASE}/projects/{project_id}/members"
    added = Client().post(url, data=json.dumps({"user_id": 21}),
                          content_type="application/json", **_auth(slug))
    assert added.status_code == 201
    assert sorted(Client().get(url, **_auth(slug)).json()) == [11, 21]
    refused = Client().delete(f"{url}/11", **_auth(slug))
    assert refused.status_code == 422 and refused.json()["code"] == "E-PRJ-02"


@pytest.mark.django_db
def test_mine_filter(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    _create(slug)
    _create(slug, code="П-016", name="Объект 16", manager_user_id=7)
    mine = Client().get(f"{BASE}/projects?mine=1", **_auth(slug)).json()
    assert [row["code"] for row in mine] == ["П-016"]


def _with_role(slug, user_id, code):
    from apps.access.models import Role, RoleAssignment, ScopeKind

    RoleAssignment.objects.get_or_create(
        company_slug=slug, user_id=user_id, role=Role.objects.get(code=code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)


@pytest.mark.django_db
def test_pm_sees_only_projects_he_takes_part_in(company_context):
    """Мастер-план A1.3: ПМ видит только проекты-участия, СН — все активные.
    Ограничение — на сервере, а не выбором клиента ``?mine=1``."""
    from apps.project.services import projects

    slug = company_context["slug"]
    own = projects.create(code="П-1", name="Свой", country_code="KZ", manager_user_id=21,
                          actor_id=1)
    other = projects.create(code="П-2", name="Чужой", country_code="KZ", manager_user_id=99,
                            actor_id=1)
    _with_role(slug, 21, "bpp-pm")
    _with_role(slug, 22, "bpp-sn")

    pm_list = Client().get(f"{BASE}/projects", **_auth(slug, 21)).json()
    assert [row["code"] for row in pm_list] == ["П-1"]
    assert Client().get(f"{BASE}/projects/{own.id}", **_auth(slug, 21)).status_code == 200
    assert Client().get(f"{BASE}/projects/{other.id}", **_auth(slug, 21)).status_code == 404
    assert Client().get(f"{BASE}/projects/{other.id}/members",
                        **_auth(slug, 21)).status_code == 404
    added = Client().post(f"{BASE}/projects/{other.id}/members", data=json.dumps({"user_id": 5}),
                          content_type="application/json", **_auth(slug, 21))
    assert added.status_code == 404

    sn_list = Client().get(f"{BASE}/projects", **_auth(slug, 22)).json()
    assert {row["code"] for row in sn_list} == {"П-1", "П-2"}


@pytest.mark.django_db
def test_malformed_project_id_is_404(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project", "full")
    assert Client().get(f"{BASE}/projects/not-a-uuid", **_auth(slug)).status_code == 404


@pytest.mark.django_db
def test_user_names_for_managers_and_members_only(company_context):
    """ФИО руководителя и участников — из учёток ``users``, а не из кадров:
    у ТД/ОД/ПМ кадровых прав нет. Чужие id (не руководитель и не участник
    ни одного проекта) не раскрываются — это не справочник пользователей."""
    from apps.users.models import User

    slug = company_context["slug"]
    boss = User.objects.create(username="boss", email="boss@x.test", first_name="Айдар",
                               last_name="Бек")
    stranger = User.objects.create(username="str", email="str@x.test", first_name="Чужой",
                                   last_name="Человек")
    assign(slug, 7, "project", "view")
    assign(slug, 7, "project.all", "view")
    assign(slug, 8, "project.projects", "full")
    created = Client().post(
        f"{BASE}/projects", content_type="application/json", **_auth(slug, 8),
        data=json.dumps({"code": "П-016", "name": "Объект", "country_code": "KZ",
                         "manager_user_id": boss.pk}))
    assert created.status_code == 201, created.content

    ids = f"{boss.pk},{stranger.pk},zzz"
    response = Client().get(f"{BASE}/user-names", {"ids": ids}, **_auth(slug))
    assert response.status_code == 200, response.content
    names = response.json()
    assert list(names) == [str(boss.pk)]
    assert "Бек" in names[str(boss.pk)]
    assert Client().get(f"{BASE}/user-names", **_auth(slug)).json() == {}


@pytest.mark.django_db
def test_user_names_do_not_open_foreign_projects_to_a_pm(company_context):
    """ПМ без ``project.all`` видит имена только из проектов, где он участник:
    состав чужого проекта перебором id не выяснить (A1.3)."""
    from apps.project.models import Project, ProjectMember
    from apps.users.models import User

    slug = company_context["slug"]
    own_boss = User.objects.create(username="ob", email="ob@x.test", first_name="Свой",
                                   last_name="Руководитель")
    foreign_boss = User.objects.create(username="fb", email="fb@x.test", first_name="Чужой",
                                       last_name="Руководитель")
    own = Project.objects.create(code="П-1", name="Свой", country_code="KZ",
                                 manager_user_id=own_boss.pk)
    foreign = Project.objects.create(code="П-2", name="Чужой", country_code="KZ",
                                     manager_user_id=foreign_boss.pk)
    ProjectMember.objects.create(project=own, user_id=own_boss.pk)
    ProjectMember.objects.create(project=own, user_id=21)
    ProjectMember.objects.create(project=foreign, user_id=foreign_boss.pk)
    _with_role(slug, 21, "bpp-pm")               # настоящий ПМ: без project.all

    response = Client().get(f"{BASE}/user-names",
                            {"ids": f"{own_boss.pk},{foreign_boss.pk}"}, **_auth(slug, 21))
    assert list(response.json()) == [str(own_boss.pk)]


@pytest.mark.django_db
def test_user_names_survive_weird_ids(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project", "view")
    assign(slug, 7, "project.all", "view")
    for ids in ("²", "٣", "99999999999999999999", "1,²,9999999999", "-5", " "):
        response = Client().get(f"{BASE}/user-names", {"ids": ids}, **_auth(slug))
        assert response.status_code == 200, (ids, response.content)
        assert response.json() == {}
