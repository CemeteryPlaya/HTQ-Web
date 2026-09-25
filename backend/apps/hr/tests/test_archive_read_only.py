"""Архивная компания — только чтение, сквозь весь стек (спека архива §1, §9).

Через настоящий Client: middleware → api_view → вьюха → схема компании.
Юнит-тесты задач 1–3 проверяют точки по отдельности; этот — что они
сложились: суперпользователь читает данные схемы архива, запись закрыта
всем и в тенантной, и в общей аппке, участник архив не видит.
"""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import auth, superuser_token, token
from apps.companies.models import Company, CompanyStatus


@pytest.fixture
def archived(company_schema):
    slug = company_schema["slug"]
    # До первого запроса теста: резолв метки хоста кэшируется на 5 с.
    Company.objects.filter(slug=slug).update(status=CompanyStatus.ARCHIVED)
    return slug


def _headers(slug, tok):
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


@pytest.mark.django_db
def test_superuser_reads_archived_company(archived):
    resp = Client().get("/api/hr/v1/departments/",
                        **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_superuser_cannot_write_to_archived_company(archived):
    resp = Client().post("/api/hr/v1/departments/", data=json.dumps({"name": "Новый"}),
                         content_type="application/json",
                         **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Компания в архиве — только чтение",
                           "code": "company_archived"}


@pytest.mark.django_db
def test_shared_app_write_is_refused_on_archived_subdomain(archived):
    """Правило одно для всех аппок, включая общие (решение заказчика 25.09)."""
    resp = Client().post("/api/messenger/v1/rooms/", data=json.dumps({"name": "x"}),
                         content_type="application/json",
                         **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 403
    assert resp.json()["code"] == "company_archived"


@pytest.mark.django_db
def test_member_of_archived_company_sees_nothing(archived):
    resp = Client().get("/api/hr/v1/departments/",
                        **_headers(archived, token(company=archived)))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Компания не найдена"}
