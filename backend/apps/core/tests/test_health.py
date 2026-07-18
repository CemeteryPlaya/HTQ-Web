import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_matches_fastapi_contract():
    resp = Client().get("/health/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "backend"
    assert "timestamp" in body


@pytest.mark.django_db
def test_ready_ok():
    resp = Client().get("/health/ready/")
    assert resp.status_code == 200
