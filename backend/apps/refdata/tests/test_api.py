"""Ручки справочников: читать — всем с ролью, править — только в управляющей компании."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import assign, token
from apps.companies.models import Company, CompanyKind

BASE = "/api/refdata/v1"


def _auth(slug, user_id=7):
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def _post(path, body, slug):
    return Client().post(f"{BASE}/{path}", data=json.dumps(body),
                         content_type="application/json", **_auth(slug))


@pytest.fixture
def holding(db):
    return Company.objects.create(slug="group-hq", name="Холдинг", kind=CompanyKind.HOLDING)


@pytest.fixture
def subsidiary(db):
    return Company.objects.create(slug="htq-kz", name="ДО", kind=CompanyKind.CONSTRUCTION)


@pytest.mark.django_db
def test_read_needs_refdata_read(holding):
    assert Client().get(f"{BASE}/currencies", **_auth(holding.slug)).status_code == 403
    assign(holding.slug, 7, "refdata", "view")
    response = Client().get(f"{BASE}/currencies", **_auth(holding.slug))
    assert response.status_code == 200
    assert "KZT" in {row["code"] for row in response.json()}


@pytest.mark.django_db
def test_can_edit_is_true_in_holding_and_false_in_subsidiary(holding, subsidiary):
    """Ответ ручки несёт ``can_edit`` на каждой строке (задача 9, A2.4):
    кнопки правки на фронте включаются им, а не отдельным запросом прав."""
    assign(holding.slug, 7, "refdata", "full")
    assign(subsidiary.slug, 7, "refdata", "full")
    in_holding = Client().get(f"{BASE}/currencies", **_auth(holding.slug)).json()
    assert in_holding and all(row["can_edit"] is True for row in in_holding)
    in_subsidiary = Client().get(f"{BASE}/currencies", **_auth(subsidiary.slug)).json()
    assert in_subsidiary and all(row["can_edit"] is False for row in in_subsidiary)


@pytest.mark.django_db
def test_edit_in_holding(holding):
    assign(holding.slug, 7, "refdata", "full")
    response = _post("uoms", {"code": "pack", "short_name": "уп", "name": "Упаковка"},
                     holding.slug)
    assert response.status_code == 201, response.content
    assert response.json()["code"] == "pack"


@pytest.mark.django_db
def test_edit_from_subsidiary_is_forbidden(subsidiary):
    assign(subsidiary.slug, 7, "refdata", "full")
    response = _post("uoms", {"code": "pack", "short_name": "уп", "name": "Упаковка"},
                     subsidiary.slug)
    assert response.status_code == 403
    assert response.json()["code"] == "E-REF-01"


@pytest.mark.django_db
def test_archive_instead_of_delete(holding):
    assign(holding.slug, 7, "refdata", "full")
    uom_id = next(row["id"] for row in
                  Client().get(f"{BASE}/uoms", **_auth(holding.slug)).json()
                  if row["code"] == "h")
    response = Client().patch(f"{BASE}/uoms/{uom_id}", data=json.dumps({"is_active": False}),
                              content_type="application/json", **_auth(holding.slug))
    assert response.status_code == 200 and response.json()["is_active"] is False
    active = Client().get(f"{BASE}/uoms?active=1", **_auth(holding.slug)).json()
    assert "h" not in {row["code"] for row in active}
    assert Client().delete(f"{BASE}/uoms/{uom_id}", **_auth(holding.slug)).status_code == 405


@pytest.mark.django_db
def test_article_code_is_unique(holding):
    assign(holding.slug, 7, "refdata", "full")
    groups = Client().get(f"{BASE}/article-groups", **_auth(holding.slug)).json()
    supply = next(g["id"] for g in groups if g["code"] == "supply")
    body = {"code": "111", "name": "Металлопрокат", "group_id": supply}
    assert _post("articles", body, holding.slug).status_code == 201
    second = _post("articles", body, holding.slug)
    assert second.status_code == 422 and second.json()["code"] == "E-REF-02"


@pytest.mark.django_db
def test_malformed_id_is_404(holding):
    assign(holding.slug, 7, "refdata", "full")
    response = Client().patch(f"{BASE}/uoms/not-a-uuid", data=json.dumps({"name": "x"}),
                              content_type="application/json", **_auth(holding.slug))
    assert response.status_code == 404
