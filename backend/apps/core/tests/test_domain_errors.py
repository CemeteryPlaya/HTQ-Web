"""Ошибка предметной области: текст для человека, код для машины (D-28)."""

import json

import pytest
from django.test import RequestFactory

from htqweb.errors import DomainError
from htqweb.http import api_view


@api_view(methods=("POST",), auth=None)
def _raises(request):
    raise DomainError("E-BUD-02", "По проекту П-015 нет утверждённого бюджета.",
                      fields=[{"field": "project", "message": "нет бюджета"}])


@api_view(methods=("POST",), auth=None)
def _conflict(request):
    raise DomainError("E-CON-01", "Документ изменён.", status=409)


@pytest.mark.django_db
def test_domain_error_becomes_the_tz_envelope():
    response = _raises(RequestFactory().post("/x"))
    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": "По проекту П-015 нет утверждённого бюджета.",
        "code": "E-BUD-02",
        "fields": [{"field": "project", "message": "нет бюджета"}],
    }


@pytest.mark.django_db
def test_domain_error_carries_its_own_status():
    response = _conflict(RequestFactory().post("/x"))
    assert (response.status_code, json.loads(response.content)["code"]) == (409, "E-CON-01")
    assert json.loads(response.content)["fields"] == []
