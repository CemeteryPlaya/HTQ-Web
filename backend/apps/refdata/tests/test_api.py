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


def _groups():
    from apps.refdata.models import ArticleGroup

    supply, _ = ArticleGroup.objects.get_or_create(
        code="supply", defaults={"name": "Снабжение", "node_key": "bpp.articles.supply"})
    pm, _ = ArticleGroup.objects.get_or_create(
        code="pm", defaults={"name": "Проектное управление", "node_key": "bpp.articles.pm"})
    return str(supply.id), str(pm.id)


@pytest.mark.django_db
def test_parent_article_of_another_group_is_refused(holding):
    """Родительская статья — только из той же группы: иначе статья одной
    группы (и её права BR-010) висела бы в дереве другой."""
    assign(holding.slug, 7, "refdata", "full")
    supply, pm = _groups()
    parent = _post("articles", {"code": "100", "name": "Материалы", "group_id": supply},
                   holding.slug)
    assert parent.status_code == 201, parent.content
    parent_id = parent.json()["id"]

    alien = _post("articles", {"code": "210", "name": "Консалтинг", "group_id": pm,
                               "parent_id": parent_id}, holding.slug)

    assert alien.status_code == 422, alien.content
    body = alien.json()
    assert body["code"] == "E-REF-05"
    assert body["fields"][0]["field"] == "parent_id"
    assert "Материалы" in body["detail"]

    own = _post("articles", {"code": "110", "name": "Металлопрокат", "group_id": supply,
                             "parent_id": parent_id}, holding.slug)
    assert own.status_code == 201, own.content
    assert own.json()["parent_id"] == parent_id


@pytest.mark.django_db
def test_unknown_parent_article_is_refused(holding):
    assign(holding.slug, 7, "refdata", "full")
    supply, _ = _groups()
    for parent_id in ("00000000-0000-0000-0000-000000000000", "not-a-uuid"):
        response = _post("articles", {"code": "120", "name": "Кабель", "group_id": supply,
                                      "parent_id": parent_id}, holding.slug)
        assert response.status_code == 422, response.content
        assert response.json()["code"] == "E-REF-05"


@pytest.mark.django_db
def test_archived_parent_article_is_refused(holding):
    """Архивная статья в новые документы не предлагается — и в родители
    новой статьи тоже не годится."""
    from apps.refdata.models import Article

    assign(holding.slug, 7, "refdata", "full")
    supply, _ = _groups()
    parent = _post("articles", {"code": "130", "name": "Кабельная продукция",
                                "group_id": supply}, holding.slug)
    assert parent.status_code == 201, parent.content
    Article.objects.filter(pk=parent.json()["id"]).update(is_active=False)

    response = _post("articles", {"code": "131", "name": "Кабель силовой", "group_id": supply,
                                  "parent_id": parent.json()["id"]}, holding.slug)

    assert response.status_code == 422, response.content
    body = response.json()
    assert body["code"] == "E-REF-05"
    assert body["fields"][0]["field"] == "parent_id"
    assert "в архиве" in body["detail"]


@pytest.mark.django_db
def test_model_clean_holds_the_parent_rule_for_django_admin():
    """django-admin сохраняет через ``full_clean()``, а не через ручку API:
    правило родителя живёт в ``Article.clean()``, иначе админка его обходит."""
    from django.core.exceptions import ValidationError

    from apps.refdata.models import Article, ArticleGroup

    supply_id, pm_id = _groups()
    supply = ArticleGroup.objects.get(pk=supply_id)
    pm = ArticleGroup.objects.get(pk=pm_id)
    root = Article.objects.create(code="140", name="Материалы", group=supply)
    child = Article.objects.create(code="141", name="Металл", group=supply, parent=root)

    alien = Article(code="240", name="Консалтинг", group=pm, parent=root)
    with pytest.raises(ValidationError) as cross_group:
        alien.full_clean()
    assert "parent" in cross_group.value.message_dict

    root.parent = root
    with pytest.raises(ValidationError):
        root.full_clean()

    # Цикл: корень под собственным потомком.
    root.parent = child
    with pytest.raises(ValidationError) as cycle:
        root.full_clean()
    assert "вложена" in cycle.value.message_dict["parent"][0]

    Article(code="142", name="Трубы", group=supply, parent=root).full_clean()


@pytest.mark.django_db
def test_child_of_a_later_archived_parent_stays_editable():
    """Архив родителя закрывает его для НОВЫХ связей; статья, привязанная к
    нему раньше, правится как прежде."""
    from apps.refdata.models import Article, ArticleGroup

    supply_id, _ = _groups()
    supply = ArticleGroup.objects.get(pk=supply_id)
    root = Article.objects.create(code="150", name="Инструмент", group=supply)
    child = Article.objects.create(code="151", name="Ручной инструмент", group=supply,
                                   parent=root)
    Article.objects.filter(pk=root.pk).update(is_active=False)

    child.refresh_from_db()
    child.name = "Инструмент ручной"
    child.full_clean()
