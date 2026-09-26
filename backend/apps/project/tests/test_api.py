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
def test_members(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.members", "full")
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
