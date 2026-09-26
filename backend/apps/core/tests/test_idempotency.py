"""Idempotency-Key: повтор записи не создаёт второй документ (AC-013, D-29)."""

import json

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from htqweb.http import api_view
from htqweb.idempotency import lock_key

CALLS: list[int] = []


@api_view(methods=("POST",), auth=None, status=201, idempotent=True)
def _create(request):
    CALLS.append(1)
    return {"id": len(CALLS)}


def _post(key: str | None = None, path: str = "/api/x"):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return _create(RequestFactory().post(path, **headers))


def _body(response):
    return json.loads(response.content)


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    cache.clear()
    yield
    CALLS.clear()


@pytest.mark.django_db
def test_same_key_replays_first_response():
    first = _post("k-1")
    second = _post("k-1")
    assert (first.status_code, _body(first)) == (201, {"id": 1})
    assert (second.status_code, _body(second)) == (201, {"id": 1})
    assert second["Idempotent-Replay"] == "true"
    assert len(CALLS) == 1


@pytest.mark.django_db
def test_other_key_or_other_path_is_a_new_request():
    _post("k-1")
    _post("k-2")
    _post("k-1", path="/api/y")
    assert len(CALLS) == 3


@pytest.mark.django_db
def test_without_key_every_request_runs():
    _post()
    _post()
    assert len(CALLS) == 2


@pytest.mark.django_db
def test_concurrent_same_key_is_rejected():
    """Второй запрос пришёл, пока первый ещё выполняется: 409, без эффекта."""
    request = RequestFactory().post("/api/x", HTTP_IDEMPOTENCY_KEY="k-busy")
    request.token = None
    cache.add(lock_key(request, "k-busy"), 1, 30)
    response = _create(RequestFactory().post("/api/x", HTTP_IDEMPOTENCY_KEY="k-busy"))
    assert response.status_code == 409
    assert _body(response)["code"] == "E-IDEM-01"
    assert CALLS == []


@pytest.mark.django_db
def test_failed_request_is_not_remembered():
    @api_view(methods=("POST",), auth=None, idempotent=True)
    def _boom(request):
        CALLS.append(1)
        raise RuntimeError("упало")

    assert _boom(RequestFactory().post("/api/z", HTTP_IDEMPOTENCY_KEY="k-z")).status_code == 500
    assert _boom(RequestFactory().post("/api/z", HTTP_IDEMPOTENCY_KEY="k-z")).status_code == 500
    assert len(CALLS) == 2
